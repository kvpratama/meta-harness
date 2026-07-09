# Part 8 — The Agent Scaffold as Harness

Part 7 made the claim that Terminal-Bench 2 (TB2) runs the *same loop* on a different kind of
harness. Now we make that concrete, the way Part 2 did for text classification. There, a candidate
was a `MemorySystem` with five methods. Here, a candidate is a **terminal-agent scaffold**: a single
`agents/<name>.py` file exposing an `AgentHarness` class. If you understand what that class is and
where you're allowed to change it, you understand the entire TB2 search space.

## The contract: subclass `Terminus2`

In text classification the fixed interface was "subclass `MemorySystem`." In TB2 the fixed interface
is "subclass `Terminus2`," Harbor's reference terminal agent. The
[SKILL.md](../reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md)
states the one hard rule and how wide the space around it is:

```text
# from reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md, line 28
**The search space is arbitrary Python code.** You can override any method, call any library, make raw API calls, add new tools, change how the LLM is called, rewrite command execution, intercept and transform observations -- anything that's expressible in Python is fair game. The only constraint is that the agent must subclass `harbor.agents.terminus_2.terminus_2.Terminus2` in the same way as `baseline_kira.py` does (for compatibility with the eval harness).
```

This plays exactly the role of the `MemorySystem` base class: one fixed shape so the evaluator can
drive any candidate interchangeably. The baseline is so thin it *is* the contract:

```python
# from reference_examples/terminal_bench_2/agents/baseline_terminus2.py, lines 1–5
"""Vanilla Terminus-2 baseline with no KIRA-specific modifications."""

from harbor.agents.terminus_2 import Terminus2

AgentHarness = Terminus2
```

Five lines. `AgentHarness = Terminus2` says "a candidate is just a name Harbor can import" — the
floor of the search space, analogous to `NoMemory` in Part 2. The other baseline,
[baseline_kira.py](../reference_examples/terminal_bench_2/agents/baseline_kira.py), is **1214
lines**: a native tool-use rewrite of Terminus2 that overrides almost everything. Those two files
bracket the space the same way `NoMemory` and `FewShotMemory` did.

```diagram
   text_classification                 terminal_bench_2
   ───────────────────                 ────────────────
   floor: NoMemory (learn nothing)     floor: baseline_terminus2 (5 lines)
   ceil : FewShotMemory (store all)    ceil : baseline_kira (1214 lines)
   base : subclass MemorySystem        base : subclass Terminus2
   candidate = agents/<name>.py        candidate = agents/<name>.py
                                        exposing AgentHarness
```

## The overridable seams

Where `MemorySystem` gave you two methods to fill (`predict`/`learn_from_batch`), `Terminus2` gives
you a set of *seams* — methods a candidate can override to change one behavior without rewriting the
whole agent. The class declaration and the seam catalog live in `baseline_kira.py`:

```python
# from reference_examples/terminal_bench_2/agents/baseline_kira.py, lines 217–227
class AgentHarness(Terminus2):
    """
    TerminusKira extends harbor's Terminus2 with native tool calling.

    Instead of prompting the model to output JSON/XML and parsing it, TerminusKira uses the `tools` parameter in LLM API calls for structured outputs.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._marker_seq = 0
        self._total_time_saved = 0.0
```

The SKILL names the seams a candidate is expected to reach for:

```text
# from reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md, lines 40–47
- `_call_llm_with_tools` - makes the litellm API call. Override to change tools, add parameters, adjust retries.
- `_parse_tool_calls` - converts raw tool call dicts to commands. Override to add new tools.
- `_execute_commands` - runs commands on tmux. Override to change execution behavior.
- `_run_agent_loop` - main episode loop. Override for structural changes.
- `_get_completion_confirmation_message` - what to ask on the "are you sure?" step.
- `_get_prompt_template_path` - path to system prompt. Override to use a custom prompt.
- `_summarize_context` - summarizes history on context overflow. Override to change summarization.
- `_execute_image_read` - handles image_read tool. Override to change multimodal behavior.
```

Each seam is a hypothesis surface. Want a different system prompt? Override
`_get_prompt_template_path`. A new tool? Extend `_parse_tool_calls`. A different context-overflow
strategy? Override `_summarize_context`. This is the analog of "change `learn_from_batch`, inherit
`predict`" from Part 2 — pick the one method your idea touches, inherit the rest.

## Two seams worth seeing

The prompt seam is the simplest — it just returns a path:

```python
# from reference_examples/terminal_bench_2/agents/baseline_kira.py, lines 308–310
    def _get_prompt_template_path(self) -> Path:
        """Return the path to the prompt template for native tool use."""
        return Path(__file__).parent.parent / "prompt-templates" / "terminus-kira.txt"
```

That points at [terminus-kira.txt](../reference_examples/terminal_bench_2/prompt-templates/terminus-kira.txt),
a plain-text template with two `.format()` placeholders the loop fills at runtime:

```text
# from reference_examples/terminal_bench_2/prompt-templates/terminus-kira.txt, lines 7–11
Task Description:
{instruction}

Current terminal state:
{terminal_state}
```

A candidate can ship its own `prompt-templates/<name>.txt` and repoint this method — a whole class
of experiments (better planning instructions, different verification checklists) needs no Python
logic at all. The richer seam is the LLM call itself, which also enforces the frozen-model boundary
from Part 1:

```python
# from reference_examples/terminal_bench_2/agents/baseline_kira.py, lines 614–622
        # Build completion kwargs
        completion_kwargs = {
            "model": self._model_name,
            "messages": messages,
            "temperature": self._temperature,
            "tools": TOOLS,
            "timeout": 900,  # 15 minutes timeout, retry on timeout
            "drop_params": True,
        }
```

Two things to notice. First, `"tools": TOOLS` — KIRA passes a **native tool schema** (defined at the
top of the file) instead of asking the model to emit JSON it then parses. That's the whole point of
this baseline over vanilla Terminus2:

```python
# from reference_examples/terminal_bench_2/agents/baseline_kira.py, lines 141–146
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "execute_commands",
            "description": _EXECUTE_COMMANDS_DESC,
```

Second, the frozen-model boundary. `AgentHarness` calls `litellm.acompletion` directly; the SKILL is
explicit that Harbor's `Chat` object is present but *not* used to make the call:

```text
# from reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md, line 126
- `AgentHarness` calls `litellm.acompletion` directly -- it does NOT use harbor's `Chat` class for LLM calls. The `Chat` object is passed in but only used for message history / token counting.
```

Just like `MemorySystem.__init__(self, llm)` injected the model, the candidate decides *what to
send* Claude Opus — the tools, the temperature, the messages — but never *which model* runs. The
search stays on the harness side of the line.

## What you may and may not touch

The freedom is bounded by the same anti-cheating spirit as text classification. The SKILL spells out
the file-level rules:

```text
# from reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md, lines 58–60
- **CAN**: edit your new `agents/<name>.py` file freely.
- **CAN**: create a new prompt template at `prompt-templates/<name>.txt` and point `_get_prompt_template_path` to it.
- **CANNOT**: modify any existing agent file, `meta_harness.py`, or `claude_wrapper.py`.
```

A candidate lives entirely in its own new file (plus an optional prompt template). It can't touch
the orchestrator or other candidates — the same isolation that let the text-classification benchmark
glob `agents/` and trust each file independently (Part 4).

## What to notice

- **The interface is a subclass, again.** "Subclass `Terminus2`, expose `AgentHarness`" is the TB2
  version of "subclass `MemorySystem`." One fixed shape lets one evaluator drive every candidate.
- **Seams replace the two-method contract.** Instead of `predict`/`learn_from_batch`, you override
  the one seam your idea touches (`_get_prompt_template_path`, `_call_llm_with_tools`, …) and inherit
  the rest of the 1214-line baseline.
- **The frozen-model boundary is still there.** The candidate assembles the `litellm` call; the
  model is fixed. `Chat` carries history and token counts, not the completion.
- **Candidates are isolated files.** CAN edit your own `agents/<name>.py` and a prompt template;
  CANNOT touch existing agents or the loop — the same per-file trust the sweep relies on.

---

*Next up: Part 9 — Evaluating on a Real Sandbox — how one candidate becomes a pass rate over trials,
why the import check grows a smoke test, and how cost and noise dictate a staged bring-up.*

## ✦ Check Your Understanding

1. In Part 2 a candidate overrode `predict`/`learn_from_batch`; here it overrides seams like
   `_get_prompt_template_path` or `_call_llm_with_tools`. What is the shared design goal that both
   the five-method contract and the seam catalog serve?
2. `baseline_terminus2.py` is 5 lines and `baseline_kira.py` is 1214. Map each onto a text
   classification baseline from Part 2, and explain what "the floor" of a search space buys you.
3. The SKILL says `AgentHarness` calls `litellm.acompletion` directly and only uses `Chat` for
   history/token counting. If a candidate tried to swap in a *different* model inside
   `_call_llm_with_tools`, which principle from Part 1 would it violate, and why would that make the
   search result meaningless?
