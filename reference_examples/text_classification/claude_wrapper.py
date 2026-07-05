"""Claude Code backend (`claude -p`) for the proposer.

Thin ClaudeRunner over the shared AgentRunner. Keeps module-level run/
build_command/TOOLS_* for back-compat with callers and the __main__ tests.
"""

import json
import re
from pathlib import Path

from agent_runner import (
    DEFAULT_LOG_DIR,
    AgentRunner,
    SessionResult,
    ToolCall,
    _make_relative,
)

_EMPTY_PLUGIN_DIR = Path(__file__).parent / ".empty_plugins"

TOOLS_READ = ["Read", "Glob", "Grep"]
TOOLS_WRITE = ["Read", "Glob", "Grep", "Edit", "Write"]
TOOLS_BASH = ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]
TOOLS_ALL = TOOLS_BASH + ["Agent", "WebSearch", "WebFetch"]


def _clean_read_output(output):
    lines = []
    for line in output.split("\n"):
        m = re.match(r"\s*\d+\u2192(.*)", line)
        lines.append(m.group(1) if m else line)
    return "\n".join(lines)


def _count_read_lines(output):
    return sum(1 for line in output.split("\n") if re.match(r"\s*\d+\u2192", line))


class ClaudeRunner(AgentRunner):
    default_tools = list(TOOLS_BASH)

    def map_tools(self, allowed_tools):
        # Claude uses its own tool names directly.
        return list(allowed_tools)

    def prepare(self, *, skill_text, system_prompt, allowed_tools, model, cwd, name):
        _EMPTY_PLUGIN_DIR.mkdir(exist_ok=True)
        if skill_text:
            prefix = f"Follow these skill instructions:\n\n{skill_text}\n\n"
            system_prompt = prefix + (system_prompt or "")
        return {"system_prompt": system_prompt}

    def build_command(self, *, prompt, model, ctx, allowed_tools, effort):
        return build_command(
            prompt,
            model or "sonnet",
            allowed_tools,
            ctx.get("system_prompt"),
            effort=effort,
        )

    def setup_env(self, env):
        # Honor existing behavior: caller manages ANTHROPIC_API_KEY / CLAUDECODE.
        return env

    def clean_read_output(self, output):
        return _clean_read_output(output)

    def on_stdout_line(self, line, live_tool_calls, progress_cb):
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return
        if event.get("type") != "assistant":
            return
        for block in event.get("message", {}).get("content", []):
            if isinstance(block, dict) and block.get("type") == "tool_use":
                live_tool_calls.append(block)
                if progress_cb:
                    inp = block.get("input", {})
                    arg = inp.get("file_path") or inp.get("pattern") or ""
                    if not arg and "command" in inp:
                        arg = inp["command"][:120]
                    if not arg and "description" in inp:
                        arg = inp["description"][:120]
                    if not arg and "prompt" in inp:
                        arg = inp["prompt"][:120]
                    progress_cb(block["name"], arg)

    def parse_events(self, stdout, prompt, model, duration, exit_code, cwd=None):
        return parse_stream_events(stdout, prompt, model, duration, exit_code, cwd=cwd)


def build_command(
    prompt,
    model="sonnet",
    allowed_tools=None,
    system_prompt=None,
    tools=None,
    disallowed_tools=None,
    disable_skills=True,
    disable_mcp=True,
    effort=None,
):
    cmd = [
        "claude",
        "--dangerously-skip-permissions",
        "-p",
        prompt,
        "--output-format",
        "stream-json",
        "--verbose",
        "--model",
        model,
        "--setting-sources",
        "",
    ]
    effective_tools = tools if tools is not None else allowed_tools
    if effective_tools:
        cmd.extend(["--tools", ",".join(effective_tools)])
    if allowed_tools:
        cmd.append("--allowedTools")
        cmd.extend(allowed_tools)
    if disallowed_tools:
        cmd.append("--disallowedTools")
        cmd.extend(disallowed_tools)
    if disable_skills:
        cmd.append("--disable-slash-commands")
    if disable_mcp:
        cmd.append("--strict-mcp-config")
    _EMPTY_PLUGIN_DIR.mkdir(exist_ok=True)
    cmd.extend(["--plugin-dir", str(_EMPTY_PLUGIN_DIR)])
    if system_prompt:
        cmd.extend(["--append-system-prompt", system_prompt])
    if effort:
        cmd.extend(["--effort", effort])
    return cmd


def parse_stream_events(stdout, prompt, model, duration, exit_code, cwd=None):
    events = []
    text_parts = []
    tool_calls = []
    tool_call_map = {}
    token_usage = {"input_tokens": 0, "output_tokens": 0}
    session_id = ""
    cost_usd = 0.0
    for line in stdout.strip().split("\n") if stdout.strip() else []:
        try:
            event = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue
        events.append(event)
        etype = event.get("type", "")
        if etype == "assistant":
            msg = event.get("message", {})
            usage = msg.get("usage", {})
            token_usage["input_tokens"] += usage.get("input_tokens", 0)
            token_usage["output_tokens"] += usage.get("output_tokens", 0)
            for cache_key in ("cache_creation_input_tokens", "cache_read_input_tokens"):
                if cache_key in usage:
                    token_usage[cache_key] = token_usage.get(cache_key, 0) + usage[cache_key]
            for block in msg.get("content", []):
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text_parts.append(block["text"])
                elif btype == "tool_use":
                    tc = ToolCall(name=block["name"], tool_id=block.get("id", ""), input=block.get("input", {}))
                    tool_calls.append(tc)
                    tool_call_map[tc.tool_id] = tc
        elif etype == "user":
            msg = event.get("message", {})
            for block in msg.get("content", []):
                if isinstance(block, dict) and block.get("type") == "tool_result":
                    tid = block.get("tool_use_id", "")
                    if tid in tool_call_map:
                        tool_call_map[tid].output = str(block.get("content", ""))
                        tool_call_map[tid].is_error = block.get("is_error", False)
        elif etype == "result":
            session_id = event.get("session_id", "")
            cost_usd = event.get("total_cost_usd", 0.0)
            result_usage = event.get("usage", {})
            if result_usage:
                token_usage["input_tokens"] = result_usage.get("input_tokens", token_usage["input_tokens"])
                token_usage["output_tokens"] = result_usage.get("output_tokens", token_usage["output_tokens"])

    files_read = {}
    files_written = {}
    for tc in tool_calls:
        if tc.name == "Read" and "file_path" in tc.input:
            path = _make_relative(tc.input["file_path"], cwd)
            lines = _count_read_lines(tc.output)
            if path in files_read:
                files_read[path]["reads"] += 1
                files_read[path]["lines"] += lines
            else:
                files_read[path] = {"reads": 1, "lines": lines}
        elif tc.name == "Write" and "file_path" in tc.input:
            path = _make_relative(tc.input["file_path"], cwd)
            content = tc.input.get("content", "")
            lines = content.count("\n") + (1 if content else 0)
            files_written[path] = {"lines_written": lines}
        elif tc.name == "Edit" and "file_path" in tc.input:
            path = _make_relative(tc.input["file_path"], cwd)
            new_str = tc.input.get("new_string", "")
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


_runner = ClaudeRunner()


def run(prompt, model="sonnet", allowed_tools=None, cwd=None, log_dir=None,
        name=None, system_prompt=None, skill_path=None, skills=None,
        skill_dir=None, timeout_seconds=None, progress=True, effort=None,
        **_ignored):
    """Run `claude -p` and return a parsed SessionResult."""
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
