"""opencode backend (`opencode run --format json`) for the proposer.

System prompt + tool allowlist are injected via a per-run generated agent file
under <cwd>/.opencode/agent/<name>.md, which is removed after the run.
"""

import json
import re
import uuid
from pathlib import Path

from agent_runner import (
    DEFAULT_LOG_DIR,
    AgentRunner,
    SessionResult,
    ToolCall,
    _make_relative,
)

# claude tool name -> opencode permission name
_TOOL_MAP = {
    "Read": "read",
    "Glob": "glob",
    "Grep": "grep",
    "Agent": "task",
    "Task": "task",
    "Write": "edit",
    "Edit": "edit",
    "Bash": "bash",
    "WebSearch": "websearch",
    "WebFetch": "webfetch",
}

_ALL_PERMS = ["bash", "read", "edit", "glob", "grep", "webfetch", "task", "todowrite", "websearch", "lsp", "skill"]

# opencode read output is wrapped as <path>..</path><type>..</type><content>\nN: line..</content>
_READ_LINE_RE = re.compile(r"^\s*\d+:\s?(.*)$")


def _clean_read_output(output):
    """Strip the <path>/<type>/<content> wrapper and 'N: ' line prefixes."""
    lines = []
    for line in output.split("\n"):
        if line in ("<content>", "</content>") or line.startswith("<path>") or line.startswith("<type>"):
            continue
        m = _READ_LINE_RE.match(line)
        lines.append(m.group(1) if m else line)
    return "\n".join(lines)


def _count_read_lines(output):
    return sum(1 for line in output.split("\n") if _READ_LINE_RE.match(line))


def map_tools(allowed_tools):
    """Map claude-style names to a deduped list of opencode permission names."""
    seen = []
    for t in allowed_tools:
        perm = _TOOL_MAP.get(t)
        if perm and perm not in seen:
            seen.append(perm)
    return seen


def build_agent_file(skill_text, system_prompt, allowed_tools, model):
    """Return the markdown content of a generated opencode agent file."""
    perms = map_tools(allowed_tools)
    tools_yaml = "\n".join(f"  {p}: true" for p in perms)
    body_parts = []
    if skill_text:
        body_parts.append(f"Follow these skill instructions:\n\n{skill_text}")
    if system_prompt:
        body_parts.append(system_prompt)
    body = "\n\n".join(body_parts) if body_parts else "You are a helpful coding agent."
    front = ["---", "description: meta-harness proposer (auto-generated)", "mode: primary"]
    if model:
        front.append(f"model: {model}")
    front.append("tools:")
    front.append(tools_yaml)
    front.append("---")
    return "\n".join(front) + "\n" + body + "\n"


def build_command(prompt, model, agent_name, effort=None, pure=True):
    cmd = ["opencode", "run", "--format", "json", "--dangerously-skip-permissions"]
    if agent_name:
        cmd.extend(["--agent", agent_name])
    if model:
        cmd.extend(["--model", model])
    if effort:
        cmd.extend(["--variant", effort])
    if pure:
        cmd.append("--pure")
    cmd.append(prompt)
    return cmd


def parse_events(stdout, prompt, model, duration, exit_code, cwd=None):
    events = []
    text_parts = []
    tool_calls = []
    token_usage = {"input_tokens": 0, "output_tokens": 0}
    session_id = ""
    cost_usd = 0.0
    saw_error = False
    for line in stdout.strip().split("\n") if stdout.strip() else []:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        events.append(event)
        etype = event.get("type", "")
        if not session_id:
            session_id = event.get("sessionID", "")
        part = event.get("part", {})
        if etype == "text":
            text_parts.append(part.get("text", ""))
        elif etype == "tool_use":
            state = part.get("state", {})
            tool_calls.append(
                ToolCall(
                    name=part.get("tool", ""),
                    tool_id=part.get("callID", ""),
                    input=state.get("input", {}) or {},
                    output=str(state.get("output", "")),
                    is_error=state.get("status") != "completed",
                )
            )
        elif etype == "step_finish":
            toks = part.get("tokens", {}) or {}
            token_usage["input_tokens"] += toks.get("input", 0)
            token_usage["output_tokens"] += toks.get("output", 0)
            cache = toks.get("cache", {}) or {}
            if cache.get("read"):
                token_usage["cache_read_input_tokens"] = token_usage.get("cache_read_input_tokens", 0) + cache["read"]
            if cache.get("write"):
                token_usage["cache_creation_input_tokens"] = token_usage.get("cache_creation_input_tokens", 0) + cache["write"]
            cost_usd += part.get("cost", 0) or 0
        elif etype == "error":
            saw_error = True

    if saw_error and exit_code == 0:
        exit_code = 1

    files_read = {}
    files_written = {}
    for tc in tool_calls:
        fp = tc.input.get("filePath")
        if tc.name == "read" and fp:
            path = _make_relative(fp, cwd)
            lines = _count_read_lines(tc.output)
            if path in files_read:
                files_read[path]["reads"] += 1
                files_read[path]["lines"] += lines
            else:
                files_read[path] = {"reads": 1, "lines": lines}
        elif tc.name == "write" and fp:
            path = _make_relative(fp, cwd)
            content = tc.input.get("content", "")
            lines = content.count("\n") + (1 if content else 0)
            files_written[path] = {"lines_written": lines}
        elif tc.name == "edit" and fp:
            path = _make_relative(fp, cwd)
            new_str = tc.input.get("newString", "") or tc.input.get("replacement", "")
            lines = new_str.count("\n") + (1 if new_str else 0)
            if path in files_written:
                files_written[path]["lines_written"] += lines
            else:
                files_written[path] = {"lines_written": lines}

    return SessionResult(
        prompt=prompt,
        text="".join(text_parts),
        tool_calls=tool_calls,
        files_read=files_read,
        files_written=files_written,
        token_usage=token_usage,
        duration_seconds=duration,
        model=model,
        session_id=session_id,
        exit_code=exit_code,
        cost_usd=cost_usd,
        raw_events=events,
    )


class OpencodeRunner(AgentRunner):
    default_tools = ["Read", "Glob", "Grep", "Edit", "Write", "Bash", "Agent"]

    def map_tools(self, allowed_tools):
        return map_tools(allowed_tools)

    def prepare(self, *, skill_text, system_prompt, allowed_tools, model, cwd, name):
        agent_name = f"mh-proposer-{name or uuid.uuid4().hex[:8]}"
        agent_dir = Path(cwd) / ".opencode" / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        agent_path = agent_dir / f"{agent_name}.md"
        agent_path.write_text(
            build_agent_file(skill_text, system_prompt, allowed_tools, model)
        )
        return {"agent": agent_name, "agent_path": agent_path}

    def build_command(self, *, prompt, model, ctx, allowed_tools, effort):
        return build_command(prompt, model, ctx["agent"], effort=effort)

    def cleanup(self, ctx):
        p = ctx.get("agent_path")
        if p and Path(p).exists():
            Path(p).unlink()

    def clean_read_output(self, output):
        return _clean_read_output(output)

    def on_stdout_line(self, line, live_tool_calls, progress_cb):
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return
        if event.get("type") != "tool_use":
            return
        part = event.get("part", {})
        live_tool_calls.append(part)
        if progress_cb:
            inp = part.get("state", {}).get("input", {}) or {}
            arg = inp.get("filePath") or inp.get("pattern") or ""
            if not arg and "command" in inp:
                arg = inp["command"][:120]
            progress_cb(part.get("tool", "tool"), arg)

    def parse_events(self, stdout, prompt, model, duration, exit_code, cwd=None):
        return parse_events(stdout, prompt, model, duration, exit_code, cwd=cwd)


_runner = OpencodeRunner()


def run(prompt, model=None, allowed_tools=None, cwd=None, log_dir=None,
        name=None, system_prompt=None, skill_path=None, skills=None,
        skill_dir=None, timeout_seconds=None, progress=True, effort=None,
        **_ignored):
    """Run `opencode run --format json` and return a parsed SessionResult."""
    return _runner.run(
        prompt=prompt,
        model=model,
        allowed_tools=allowed_tools,
        cwd=cwd,
        log_dir=log_dir or DEFAULT_LOG_DIR,
        name=name,
        system_prompt=system_prompt,
        skill_path=skill_path,
        skills=skills,
        skill_dir=skill_dir,
        timeout_seconds=timeout_seconds,
        progress=progress,
        effort=effort,
    )
