# Part 10 — The Proposer Backends

Part 5 introduced the proposer: an LLM coding agent, run as a subprocess with a SKILL document as
its prior, whose job is to *write the next candidate*. TB2 keeps that idea exactly — but makes the
agent **pluggable**. The same iteration can be driven by Claude Code or by opencode, behind one
interface. This part is the TB2 analog of Part 5, with the extra structure that pluggability
requires.

## The prior: one SKILL, two rules

As in Part 5, the domain knowledge lives in a
[SKILL.md](../reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md)
injected into the agent's system prompt. It defines the job as **analyze → implement → write
`pending_eval.json`**, and — crucially — tells the agent it does *not* run benchmarks:

```text
# from reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md, line 10
**You do NOT run benchmarks.** You analyze results + failed trajectories, propose agent variants, and implement them. The outer loop (`meta_harness.py`) handles benchmarking.
```

Where Part 5's skill fought *parameter tuning*, TB2's skill fights *overfitting to specific tasks* —
the same "keep the search honest" instinct, adapted to a domain where tasks have names an agent could
cheat toward:

```text
# from reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md, lines 17–20
### Anti-overfitting rules

- **No task-specific hints.** Do not hardcode knowledge about specific tasks. Agents must be general-purpose.
- **Never mention task names** in agent code, prompts, or comments. No references like "if task contains 'async'" or "for polyglot tasks." If your improvement only helps one task, it's too specific.
```

The handoff back to the loop is also identical in spirit to Part 5: success is a file on disk. The
skill instructs the agent to write a manifest pairing each candidate with a falsifiable hypothesis:

```json
# from reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md, lines 106–117
{
  "iteration": <N>,
  "candidates": [
    {
      "name": "<name>",
      "import_path": "agents.<name>:AgentHarness",
      "hypothesis": "<falsifiable claim>",
      "changes": "<what was changed>",
      "expected_efficiency": "<expected token/turn impact>"
    }
  ]
}
```

## The `AgentRunner` ABC: seams for a CLI agent

Part 5 had one wrapper (`claude_wrapper`). TB2 factors the *shared* orchestration of "run a coding
CLI once" into an abstract base class, [AgentRunner](../reference_examples/terminal_bench_2/agent_runner.py),
and gives each backend a set of seams to fill — the same override-one-method pattern you saw for the
agent scaffold in Part 8:

```python
# from reference_examples/terminal_bench_2/agent_runner.py, lines 317–337
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
```

Two more seams have safe defaults, so a backend only overrides them if it needs to:

```python
# from reference_examples/terminal_bench_2/agent_runner.py, lines 343–348
    def cleanup(self, ctx):
        """Tear down anything prepare() created. Default: no-op."""

    def setup_env(self, env):
        """Mutate/return the subprocess environment. Default: unchanged."""
        return env
```

## Shared plumbing every backend gets for free

The base class's `run()` method wires the seams together and hands back a normalized result. Three
pieces of shared machinery matter. `SessionResult` is the uniform return shape — no matter which CLI
ran, the loop sees the same fields:

```python
# from reference_examples/terminal_bench_2/agent_runner.py, lines 33–46
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
```

`_stream_subprocess` runs the CLI and streams its stdout line-by-line through the backend's
`on_stdout_line` seam, so live tool-use is visible during a long proposer run:

```python
# from reference_examples/terminal_bench_2/agent_runner.py, lines 256–261
def _stream_subprocess(cmd, cwd, env, timeout_seconds, on_stdout_line):
    """Run cmd, stream stdout/stderr via background threads.

    Calls on_stdout_line(line) for each stdout line. Returns
    (stdout, stderr, exit_code, duration).
    """
```

And `log_session` (line 164) writes each run to a timestamped directory — the experience trail the
onboarding questionnaire (Part 7) asked every domain to keep.

```diagram
                        AgentRunner.run()  (shared)
   ┌───────────────────────────────────────────────────────────┐
   │  prepare ─► build_command ─► _stream_subprocess ─► parse    │
   │     │            │              │  on_stdout_line    │      │
   │     │            │              ▼                    ▼      │
   │  cleanup    setup_env      live progress       SessionResult│
   └──────┬────────────────────────────────────────────┬───────┘
          │ seams filled per backend                    │ log_session
     ┌────┴─────┐                                  ┌─────┴─────┐
     │ Claude   │                                  │ opencode  │
     │ Runner   │                                  │ Runner    │
     └──────────┘                                  └───────────┘
```

## `ClaudeRunner`: the thin backend

Claude Code uses its own tool names and takes a system prompt directly, so most seams are trivial.
`map_tools` is the identity, and `prepare` just prepends the skill text to the system prompt:

```python
# from reference_examples/terminal_bench_2/claude_wrapper.py, lines 44–53
    def map_tools(self, allowed_tools):
        # Claude uses its own tool names directly.
        return list(allowed_tools)

    def prepare(self, *, skill_text, system_prompt, allowed_tools, model, cwd, name):
        _EMPTY_PLUGIN_DIR.mkdir(exist_ok=True)
        if skill_text:
            prefix = f"Follow these skill instructions:\n\n{skill_text}\n\n"
            system_prompt = prefix + (system_prompt or "")
        return {"system_prompt": system_prompt}
```

This is the same injection Part 5 showed (`"Follow these skill instructions..."`) — now expressed as
one seam of a shared runner rather than inline wrapper code.

## `OpencodeRunner`: the seams earn their keep

opencode can't take a system prompt on the command line. Its `prepare` seam instead **generates a
temporary agent file** on disk — carrying the skill text, tool permissions, and model — under
`.opencode/agent/<name>.md`:

```python
# from reference_examples/terminal_bench_2/opencode_wrapper.py, lines 193–201
    def prepare(self, *, skill_text, system_prompt, allowed_tools, model, cwd, name):
        agent_name = f"mh-proposer-{name or uuid.uuid4().hex[:8]}"
        agent_dir = Path(cwd) / ".opencode" / "agent"
        agent_dir.mkdir(parents=True, exist_ok=True)
        agent_path = agent_dir / f"{agent_name}.md"
        agent_path.write_text(
            build_agent_file(skill_text, system_prompt, allowed_tools, model)
        )
        return {"agent": agent_name, "agent_path": agent_path}
```

Because `prepare` wrote a file, the `cleanup` seam removes it after the run — the reason `cleanup`
exists in the ABC at all:

```python
# from reference_examples/terminal_bench_2/opencode_wrapper.py, lines 206–209
    def cleanup(self, ctx):
        p = ctx.get("agent_path")
        if p and Path(p).exists():
            Path(p).unlink()
```

The generated file's shape (YAML front-matter with per-tool permissions, then the skill body) is
built by `build_agent_file` (line 65), whose `perms = map_tools(allowed_tools)` translates Claude's
tool names into opencode's permission names — the exact thing the `map_tools` seam exists for.

## Wiring: `propose()` picks a backend

The outer loop calls one function, `propose()`, which routes to the chosen backend and — as in
Part 5 — returns success purely by checking that `pending_eval.json` now exists:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 410–415
def propose(task_prompt, iteration, backend="claude", model=None, effort="max", timeout=2400):
    """Run the selected proposer backend. Returns True if pending_eval.json exists."""
    skills = [str(EVOLVE_DIR / ".claude/skills/meta-harness-terminal-bench-2")]
    log_dir = str(LOGS_DIR / f"{backend}_sessions")
    if backend == "opencode":
        result = opencode_wrapper.run(
```

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 449–450
    result.show()
    return PENDING_EVAL.exists()
```

The backend is a command-line choice, exposed through three flags:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 912–929
    parser.add_argument(
        "--proposer",
        choices=["claude", "opencode"],
        default="claude",
        help="Proposer backend (default: claude)",
    )
    parser.add_argument(
        "--proposer-model",
        type=str,
        default=None,
        help="Proposer model. Default: 'opus' for claude; required 'provider/model' for opencode.",
    )
    parser.add_argument(
        "--proposer-effort",
        type=str,
        default="max",
        help="Proposer reasoning effort/variant (default: max)",
    )
```

## What to notice

- **Same role as Part 5, made pluggable.** The proposer is still a tool-using coding agent whose
  only output that matters is `pending_eval.json`; TB2 just lets you swap which agent CLI plays that
  role.
- **The ABC factors out the shared 90%.** `AgentRunner.run()` handles streaming, logging, and a
  uniform `SessionResult`; each backend fills only the seams where CLIs genuinely differ.
- **Seams have safe defaults for a reason.** `cleanup`/`setup_env` are no-ops until a backend needs
  them — opencode's generated-then-deleted agent file is exactly the case `cleanup` was designed for.
- **One prior, two backends.** The single SKILL.md steers whichever agent runs; its anti-overfitting
  rules are the TB2 counterpart of Part 5's anti-parameter-tuning rules.

---

*Next up: Part 11 — The TB2 Evolution Loop — how baselines, propose→validate→smoke→benchmark, and the
frontier tie together into the same outer loop as Parts 4 & 6, and the series finale.*

## ✦ Check Your Understanding

1. Both `ClaudeRunner` and `OpencodeRunner` implement the same `AgentRunner` seams, yet only opencode
   overrides `cleanup`. Explain why, tracing it back to what each backend's `prepare` does.
2. In Part 5 the proposer's success was "`pending_eval.json` exists." TB2's `propose()` returns the
   same check. Why is a file-on-disk contract more robust than trusting the agent's return value or
   its printed summary?
3. Try it: suppose you wanted to add a third backend (say, a local model via some new CLI). Which
   `AgentRunner` seams would you *have* to implement, which could you inherit, and what would you put
   in `prepare`/`cleanup` if the CLI needed a config file written first?
