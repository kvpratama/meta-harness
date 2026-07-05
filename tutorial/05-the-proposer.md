# Part 5 — The Proposer: an Agent That Writes Code

So far the candidate harnesses have appeared by magic — Part 4 just globbed whatever `.py` files
were in `agents/`. This part is where they come from. Meta-Harness doesn't mutate code with
templates or genetic operators; it runs an **LLM coding agent** as a subprocess, hands it the
search history and a skill document, and lets it *write new Python files*. This is the move that
makes the framework "automated search over harnesses" rather than a parameter sweep.

## Running an agent as a subprocess

The outer loop calls one function to get new candidates. It shells out to the Claude Code CLI
through a wrapper, pointing it at a skill and a working directory:

```python
# from reference_examples/text_classification/meta_harness.py, lines 156–166
    result = claude_wrapper.run(
        prompt=task_prompt,
        model="opus",
        allowed_tools=PROPOSER_ALLOWED_TOOLS,
        skills=[str(EVOLVE_DIR / ".claude/skills/meta-harness")],
        cwd=str(EVOLVE_DIR),
        log_dir=str(LOGS_DIR / "claude_sessions"),
        name=f"iter{iteration}",
        timeout_seconds=timeout,
        effort="max",
    )
```

The proposer is just *the model behind a coding agent*, given write access to the repo. Two details
matter. First, `allowed_tools` restricts what the agent can do (read, grep, write, edit, run bash) —
it's a real agent, not a single completion. Second, the function's success condition is purely a
side effect on disk:

```python
# from reference_examples/text_classification/meta_harness.py, lines 151–152, 176
def propose_claude(task_prompt, iteration, timeout=2400):
    """Returns True if candidates were produced (pending_eval.json exists)."""
    return PENDING_EVAL.exists()
```

The proposer "succeeded" if and only if it left a `pending_eval.json` behind. The contract between
the proposer and the orchestrator is **files on disk**, not a return value — the same
filesystem-as-API philosophy from Part 4.

## The skill is the proposer's prior

How does a generic coding agent know to write *memory systems* — and good ones? Through the
[SKILL.md](../reference_examples/text_classification/.claude/skills/meta-harness/SKILL.md)
file, which the wrapper injects directly into the agent's system prompt:

```python
# from reference_examples/text_classification/claude_wrapper.py, lines 551–558
    # Inject skill content into system prompt
    skill_info = all_skills if all_skills else None
    if all_skills:
        skill_text = "\n\n".join(
            f"## Skill: {s['name']}\n{s['content']}" for s in all_skills
        )
        prefix = f"Follow these skill instructions:\n\n{skill_text}\n\n"
        system_prompt = prefix + (system_prompt or "")
```

The skill is the *domain knowledge* of the search. It tells the agent the `MemorySystem` interface
(Part 2), where to read history, how many candidates to produce, and — most importantly — what
makes a candidate *worth evaluating*. The single most important rules in it exist to prevent the
laziest possible behavior:

```text
# from reference_examples/text_classification/.claude/skills/meta-harness/SKILL.md, lines 19–30
### Anti-parameter-tuning rules

The most common failure mode is creating systems that are just parameter variants of existing ones. Check `evolution_summary.jsonl` for what's been tried — parameter sweeps (pool sizes, retrieval counts, context budgets, similarity metrics) almost always regress or tie.

**Good candidates change a fundamental mechanism:**

- A new retrieval algorithm (e.g. contrastive pairs, diversity-aware selection, graph-based traversal)
- A new prompt architecture (e.g. organize by confusion clusters instead of listing examples sequentially)
- A new learning strategy (e.g. LLM-generated lesson summaries instead of raw example storage)
- A new memory structure (e.g. separate fast/slow pools, hierarchical organization, compressed representations)

**Bad candidates just tune numbers.** If the logic in `predict()` and `learn_from_batch()` is identical to the base except for constants, it's a parameter variant. Rewrite with a genuinely novel mechanism.
```

This is the heart of why Meta-Harness uses an LLM and not a numeric optimizer: the search space is
*mechanisms*, not hyperparameters. The skill actively pushes the agent away from "what if the pool
size were 80 instead of 50" and toward "what if we stored LLM-summarized lessons instead of raw
examples." A second set of **anti-overfitting** rules forbids dataset-specific hacks, so candidates
stay general-purpose — keeping the search honest in the same spirit as the val/test split.

## The handoff back to the loop

When the proposer finishes, it writes a manifest describing each candidate it created:

```json
# from reference_examples/text_classification/.claude/skills/meta-harness/SKILL.md, lines 86-99
{
  "iteration": <N>,
  "candidates": [
    {
      "name": "<snake_case_name>",
      "file": "agents/<name>.py",
      "hypothesis": "<falsifiable claim>",
      "axis": "exploitation|exploration",
      "base_system": "<what it builds on>",
      "components": ["tag1", "tag2", "..."]
    }
  ]
}
```

Each entry pairs a code file with a **falsifiable hypothesis** — a prediction the upcoming benchmark
will confirm or refute. That hypothesis is what later turns a pile of accuracy numbers into
*learning*: the outer loop records whether each bet paid off, and feeds that record back to the next
proposer call. The wrapper is even built to harvest such JSON blocks straight out of the agent's
response text:

```python
# from reference_examples/text_classification/claude_wrapper.py, lines 294–302
def _extract_json_blocks(text):
    """Extract named JSON code blocks from response text.

    Looks for patterns like:
        **`logs/pending_eval.json`:**
        ```json
        { ... }
        ```
    Returns list of (filename, parsed_json) tuples.
    """
```

## What to notice

- **The proposer is a tool-using agent, not a prompt.** It reads files, runs commands, and writes
  code under a restricted toolset — that's why it can prototype and self-correct.
- **Files are the API.** Success = `pending_eval.json` exists; candidates = new files in `agents/`.
  The orchestrator never inspects the agent's reasoning, only its artifacts.
- **The skill encodes the search strategy.** Injected as a system-prompt prefix, it defines the
  interface, demands novel *mechanisms* over parameter tweaks, and bans dataset-specific cheating.
- **Every candidate ships a hypothesis.** Pairing code with a falsifiable claim is what lets the
  loop convert results into accumulated knowledge (Part 6).

---

*Next up: Part 6 — Tying It Together — the outer orchestrator's phases (baselines → propose → validate → benchmark → frontier → history) and how `evolution_summary.jsonl` closes the loop.*

## ✦ Check Your Understanding

1. In your own words, why does Meta-Harness use an LLM coding agent as the proposer instead of a
   numeric hyperparameter optimizer? What kind of change is the search actually looking for?
2. The skill's anti-parameter-tuning and anti-overfitting rules don't change a single line of the
   orchestrator. Where do they take effect, and what failure mode does each one prevent?
3. Try it: imagine writing a skill to evolve a *different* kind of harness (say, a retrieval
   pipeline). Which sections of this SKILL.md would you keep almost verbatim, and which are specific
   to memory systems and would need rewriting?
