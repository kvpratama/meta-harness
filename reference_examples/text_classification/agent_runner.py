"""Shared base for agentic-CLI proposer wrappers (Claude Code, opencode).

Holds the backend-agnostic pieces: data classes, subprocess streaming,
logging, skill loading, and the AgentRunner orchestration. Backend-specific
behavior (command building, event parsing, tool naming, system-prompt/tool
injection) lives in subclasses.
"""

import json
import os
import queue
import re
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_LOG_DIR = os.environ.get("CLAUDE_WRAPPER_LOG_DIR", "experience")


@dataclass
class ToolCall:
    name: str
    tool_id: str
    input: dict
    output: str = ""
    is_error: bool = False


@dataclass
class SessionResult:
    prompt: str
    text: str
    tool_calls: list
    files_read: dict
    files_written: dict
    token_usage: dict
    duration_seconds: float
    model: str
    session_id: str
    exit_code: int
    cost_usd: float
    raw_events: list
    command: list = None
    cwd: str = None
    stderr: str = ""
    skill: dict = None
    name: str = None
    log_dir: str = None

    def show(self):
        """Print compact one-line-per-event summary."""
        if self.exit_code != 0:
            print(f"  FAILED (exit={self.exit_code})")
            print(f"  {(self.stderr or 'No stderr.')[:300]}")
            return
        for tc in self.tool_calls:
            inp = tc.input
            arg = inp.get("file_path") or inp.get("filePath") or inp.get("pattern") or ""
            if not arg and "command" in inp:
                arg = inp["command"][:120]
            if not arg and "description" in inp:
                arg = inp["description"][:120]
            if not arg and "prompt" in inp:
                arg = inp["prompt"][:120]
            err = " ERR" if tc.is_error else ""
            print(f"  tool: {tc.name}({arg}){err}")
        text = self.text.strip().replace("\n", " ")
        if text:
            print(f"  text: {text[:200]}")
        if self.files_read:
            items = ", ".join(
                f"{p}({v['reads']}x, {v['lines']}L)" for p, v in self.files_read.items()
            )
            print(f"  read: {items}")
        if self.files_written:
            items = ", ".join(
                f"{p}({v['lines_written']}L)" for p, v in self.files_written.items()
            )
            print(f"  wrote: {items}")
        print(
            f"  {self.token_usage['input_tokens']}in/"
            f"{self.token_usage['output_tokens']}out  "
            f"${self.cost_usd:.4f}  {self.duration_seconds:.1f}s"
        )


def _slugify(text, max_words=4):
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
    return "-".join(words[:max_words]) or "run"


def _make_relative(filepath, cwd):
    if not cwd or not filepath:
        return filepath
    try:
        return os.path.relpath(filepath, cwd)
    except ValueError:
        return filepath


def _extract_json_blocks(text):
    """Extract named ```json code blocks from response text.

    Returns list of (filename, parsed_json) tuples.
    """
    results = []
    pattern = re.compile(
        r"(?:\*\*`?([^`*\n]+\.json)`?\*\*[: \t]*\n)?"
        r"```json\s*\n(.*?)```",
        re.DOTALL,
    )
    for m in pattern.finditer(text):
        name_hint = m.group(1)
        body = m.group(2).strip()
        try:
            parsed = json.loads(body)
        except (json.JSONDecodeError, ValueError):
            continue
        filename = Path(name_hint).name if name_hint else None
        results.append((filename, parsed))
    return results


def load_skill(skill_path):
    path = Path(skill_path)
    if path.exists():
        return path.read_text()
    return None


def load_skills(skills, skill_dir=None):
    if skill_dir is None:
        skill_dir = ".claude/skills"
    skill_dir = Path(skill_dir)
    loaded = []
    for s in skills:
        p = Path(s)
        if p.is_dir() and (p / "SKILL.md").is_file():
            skill_file = p / "SKILL.md"
            loaded.append(
                {"path": str(skill_file), "name": p.name, "content": skill_file.read_text()}
            )
        elif p.is_dir():
            for md in sorted(p.glob("*.md")):
                loaded.append(
                    {"path": str(md), "name": md.stem, "content": md.read_text()}
                )
        elif p.is_file():
            loaded.append({"path": str(p), "name": p.stem, "content": p.read_text()})
        else:
            candidates = [skill_dir / s / "SKILL.md", skill_dir / s, skill_dir / f"{s}.md"]
            for c in candidates:
                if c.is_file():
                    name = c.parent.name if c.name == "SKILL.md" else c.stem
                    loaded.append({"path": str(c), "name": name, "content": c.read_text()})
                    break
    return loaded


def log_session(result, log_dir, clean_read=None):
    """Write session to a directory. Returns the directory path.

    clean_read: optional callable(output)->str used to strip line-number
                prefixes from Read tool output (backend-specific).
    """
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    slug = result.name or _slugify(result.prompt)
    run_dir = Path(log_dir) / f"{ts}_{slug}"
    run_dir.mkdir(parents=True, exist_ok=True)

    meta = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt": result.prompt,
        "model": result.model,
        "session_id": result.session_id,
        "exit_code": result.exit_code,
        "duration_seconds": round(result.duration_seconds, 2),
        "cost_usd": result.cost_usd,
        "token_usage": result.token_usage,
        "command": result.command,
        "cwd": result.cwd,
        "skill": result.skill,
        "files_read": result.files_read,
        "files_written": result.files_written,
        "tool_summary": [
            f"{tc.name}({'ERR ' if tc.is_error else ''}"
            f"{tc.input.get('file_path') or tc.input.get('filePath') or tc.input.get('pattern') or tc.input.get('command', '')[:120] or tc.input.get('description', '')[:120]})"
            for tc in result.tool_calls
        ],
    }
    if result.stderr:
        meta["stderr"] = result.stderr
    (run_dir / "meta.json").write_text(json.dumps(meta, indent=2, default=str))

    if result.text:
        (run_dir / "response.md").write_text(result.text)
        json_blocks = _extract_json_blocks(result.text)
        if json_blocks:
            art_dir = run_dir / "artifacts"
            art_dir.mkdir(exist_ok=True)
            for i, (name, data) in enumerate(json_blocks, 1):
                fname = name or f"{i:03d}.json"
                (art_dir / fname).write_text(json.dumps(data, indent=2) + "\n")

    if result.raw_events:
        lines = [json.dumps(e, default=str) for e in result.raw_events]
        (run_dir / "events.jsonl").write_text("\n".join(lines) + "\n")

    if result.tool_calls:
        tools_dir = run_dir / "tools"
        tools_dir.mkdir(exist_ok=True)
        for i, tc in enumerate(result.tool_calls, 1):
            parts = []
            file_path = tc.input.get("file_path") or tc.input.get("filePath") or ""
            if file_path:
                file_path = _make_relative(file_path, result.cwd)
            header = f"{tc.name}: {file_path}" if file_path else tc.name
            if tc.is_error:
                header += " [ERROR]"
            parts.append(header)
            parts.append("")
            for k, v in tc.input.items():
                if k in ("file_path", "filePath"):
                    continue
                val = str(v)
                if "\n" in val or len(val) > 80:
                    parts.append(f"{k}:")
                    parts.append(val)
                    parts.append("")
                else:
                    parts.append(f"{k}: {v}")
            if tc.output:
                is_read = tc.name.lower() == "read"
                output = clean_read(tc.output) if (is_read and clean_read) else tc.output
                parts.append("")
                parts.append("--- output ---")
                parts.append(output)
            (tools_dir / f"{i:03d}_{tc.name}.txt").write_text("\n".join(parts))

    result.log_dir = str(run_dir)
    return str(run_dir)


def _enqueue_lines(pipe, q, stream_name):
    try:
        for line in iter(pipe.readline, ""):
            q.put((stream_name, line))
    finally:
        pipe.close()


def _stream_subprocess(cmd, cwd, env, timeout_seconds, on_stdout_line):
    """Run cmd, stream stdout/stderr via background threads.

    Calls on_stdout_line(line) for each stdout line. Returns
    (stdout, stderr, exit_code, duration).
    """
    start = time.time()
    stdout_lines = []
    stderr_lines = []
    exit_code = 0
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            text=True,
            cwd=cwd,
            env=env,
        )
        deadline = start + timeout_seconds if timeout_seconds else None
        q = queue.Queue()
        t_out = threading.Thread(target=_enqueue_lines, args=(proc.stdout, q, "stdout"), daemon=True)
        t_err = threading.Thread(target=_enqueue_lines, args=(proc.stderr, q, "stderr"), daemon=True)
        t_out.start()
        t_err.start()
        while True:
            if deadline and time.time() > deadline:
                proc.kill()
                stderr_lines.append(f"\nProcess timed out after {timeout_seconds} seconds.")
                exit_code = 124
                break
            try:
                stream_name, line = q.get(timeout=0.1)
            except queue.Empty:
                if proc.poll() is not None:
                    break
                continue
            if stream_name == "stdout":
                stdout_lines.append(line)
                if on_stdout_line:
                    on_stdout_line(line)
            else:
                stderr_lines.append(line)
        proc.wait()
        if exit_code == 0:
            exit_code = proc.returncode
    except FileNotFoundError as e:
        stderr_lines = [str(e)]
        exit_code = 127
    duration = time.time() - start
    return "".join(stdout_lines), "".join(stderr_lines), exit_code, duration


class AgentRunner(ABC):
    """Base class orchestrating a one-shot agentic CLI proposer run."""

    #: subclass sets the default allowed tool set (claude tool names)
    default_tools = ["Read", "Glob", "Grep", "Edit", "Write", "Bash"]

    # ---- backend seams ----
    @abstractmethod
    def map_tools(self, allowed_tools):
        """Map claude-style tool names to backend permission names."""

    @abstractmethod
    def prepare(self, *, skill_text, system_prompt, allowed_tools, model, cwd, name):
        """Backend setup before the command runs. Returns a ctx dict consumed
        by build_command. May write files (cleaned up by cleanup())."""

    @abstractmethod
    def build_command(self, *, prompt, model, ctx, allowed_tools, effort):
        """Return the argv list for the CLI invocation."""

    @abstractmethod
    def parse_events(self, stdout, prompt, model, duration, exit_code, cwd=None):
        """Parse CLI stdout into a SessionResult."""

    @abstractmethod
    def on_stdout_line(self, line, live_tool_calls, progress_cb):
        """Handle one streamed stdout line: update live_tool_calls and invoke
        progress_cb for display. Backend-specific because event schemas differ."""

    def clean_read_output(self, output):
        """Strip line-number prefixes from Read output (backend-specific)."""
        return output

    def cleanup(self, ctx):
        """Tear down anything prepare() created. Default: no-op."""

    def setup_env(self, env):
        """Mutate/return the subprocess environment. Default: unchanged."""
        return env

    def run(
        self,
        prompt,
        model=None,
        allowed_tools=None,
        cwd=None,
        log_dir=None,
        name=None,
        system_prompt=None,
        skill_path=None,
        skills=None,
        skill_dir=None,
        timeout_seconds=None,
        progress=True,
        effort=None,
    ):
        if log_dir is None:
            log_dir = DEFAULT_LOG_DIR
        if allowed_tools is None:
            allowed_tools = list(self.default_tools)

        all_skills = []
        if skill_path:
            content = load_skill(skill_path)
            if content:
                all_skills.append({"path": skill_path, "name": Path(skill_path).stem, "content": content})
        if skills:
            all_skills.extend(load_skills(skills, skill_dir))

        skill_info = all_skills if all_skills else None
        skill_text = ""
        if all_skills:
            skill_text = "\n\n".join(f"## Skill: {s['name']}\n{s['content']}" for s in all_skills)

        effective_cwd = cwd or os.getcwd()
        ctx = self.prepare(
            skill_text=skill_text,
            system_prompt=system_prompt,
            allowed_tools=allowed_tools,
            model=model,
            cwd=effective_cwd,
            name=name,
        )
        cmd = self.build_command(
            prompt=prompt, model=model, ctx=ctx, allowed_tools=allowed_tools, effort=effort
        )

        env = self.setup_env(os.environ.copy())

        if progress is True:
            progress_cb = self._default_progress
        elif callable(progress):
            progress_cb = progress
        else:
            progress_cb = None

        live_tool_calls = []

        def _on_line(line):
            self.on_stdout_line(line, live_tool_calls, progress_cb)

        try:
            stdout, stderr, exit_code, duration = _stream_subprocess(
                cmd, cwd, env, timeout_seconds, _on_line
            )
        finally:
            self.cleanup(ctx)

        result = self.parse_events(stdout, prompt, model, duration, exit_code, cwd=effective_cwd)
        result.command = cmd
        result.cwd = effective_cwd
        result.stderr = stderr
        result.skill = skill_info
        result.name = name
        log_session(result, log_dir, clean_read=self.clean_read_output)
        return result

    @staticmethod
    def _default_progress(name, arg):
        arg = (arg or "").replace("\n", " ").strip()
        print(f"  {name}({arg[:120]})", flush=True)
