# Part 7 — Generalizing to a New Domain: Terminal-Bench 2 & Onboarding

Everything so far used one example: memory systems for text classification. The real claim of
Meta-Harness is that the *loop* — propose, evaluate on validation, track a frontier, feed history
back — is domain-independent. To prove it, the repo ships a second experiment that looks nothing
like the first on the surface: evolving the **scaffold of a terminal-using coding agent** on
[Terminal-Bench 2](../reference_examples/terminal_bench_2/README.md).
Same skeleton, different flesh.

## Same loop, different "harness"

In Part 2, a harness was a `MemorySystem` with five methods. In Terminal-Bench 2, a harness is an
**agent scaffold** — and the search space is wider:

```text
# from reference_examples/terminal_bench_2/.claude/skills/meta-harness-terminal-bench-2/SKILL.md, lines 26–28
You are evolving the **AgentHarness** agent scaffold for Terminal-Bench 2. It is located in `agents/baseline_kira.py`.

**The search space is arbitrary Python code.** You can override any method, call any library, make raw API calls, add new tools, change how the LLM is called, rewrite command execution, intercept and transform observations -- anything that's expressible in Python is fair game. The only constraint is that the agent must subclass `harbor.agents.terminus_2.terminus_2.Terminus2` in the same way as `baseline_kira.py` does (for compatibility with the eval harness).
```

This is the exact role the `MemorySystem` base class played: one fixed interface every candidate
must satisfy so the evaluator can drive them interchangeably. Here the interface is "subclass
`Terminus2`," and the baseline is so minimal it makes the point on its own:

```python
# from reference_examples/terminal_bench_2/agents/baseline_terminus2.py, lines 1–5
"""Vanilla Terminus-2 baseline with no KIRA-specific modifications."""

from harbor.agents.terminus_2 import Terminus2

AgentHarness = Terminus2
```

A candidate is just a Python module exposing an `AgentHarness` class — directly analogous to a file
in `agents/` exposing a `MemorySystem` subclass. The proposer copies the baseline and overrides
methods (the prompt template, the tool schema, how observations are summarized) instead of editing
`predict`/`learn_from_batch`.

## The loop is structurally identical

Open [terminal_bench_2/meta_harness.py](../reference_examples/terminal_bench_2/meta_harness.py)
and you'll recognize every moving part from Parts 4–6: a baselines phase, a propose→validate→
benchmark→frontier iteration, a `frontier_val.json`, an `evolution_summary.jsonl`, and a final pass.
What changes is the *vocabulary of evaluation*, declared as a handful of constants:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 93–101
EVAL_TASK_SET = "full"
N_EVAL_TASKS = 89  # full official TB2 dataset used in the paper runs

SMOKE_TEST_TASK = "extract-elf"  # simple task, reliably fast

DATASET = "terminal-bench@2.0"
MODEL = "anthropic/claude-opus-4-6"
DEFAULT_SEARCH_TRIALS = 2
DEFAULT_CONCURRENCY = 50
```

The differences are domain economics, not architecture. Accuracy becomes **pass rate over trials**
(terminal tasks are stochastic, so each is attempted `DEFAULT_SEARCH_TRIALS` times). The cheap
import-check from Part 6 is joined by a **smoke test** (`extract-elf`) that actually runs the agent
on one easy task to catch runtime crashes — necessary because a scaffold can import fine yet
deadlock in the agent loop. And an evaluation here costs minutes on a real sandbox, not a few model
calls, so the bring-up path is "smoke → 30-task hard subset → full sweep." The skeleton is the same;
only the dials moved.

```diagram
   text_classification              terminal_bench_2
   ───────────────────              ────────────────
   harness = MemorySystem           harness = AgentHarness (subclass Terminus2)
   metric  = accuracy               metric  = pass rate over N trials
   gate    = import check           gate    = import check + smoke task
   eval    = a few model calls      eval    = minutes on a real sandbox
   ─────────────  SAME LOOP: propose → validate → benchmark → frontier → history
```

## Starting your own domain: ONBOARDING.md

How do you get from "I have a task" to a working third example? The repo answers this with a
conversation, not a code template. [ONBOARDING.md](../ONBOARDING.md)
is a prompt you hand to a coding assistant; it interviews you and produces a `domain_spec.md`. The
questions it forces you to answer are exactly the design decisions every part of this series exposed:

```text
# from ONBOARDING.md, lines 54–66
- What is the cleanest base Python class or API shape for that harness?
- How would we test interface compliance?
- What changes are explicitly out of scope?

### 3. Evaluation

- What is the search-set evaluation?
- What is the held-out test evaluation, if any?
- What metric or metrics matter?
- What secondary metrics matter: latency, context cost, API spend, timeout success, etc.?
- How noisy is evaluation?
- How long does one candidate evaluation take?
- Is there memorization or contamination risk? If so, how will we mitigate it?
```

Read that list against the series. "Base Python class for the harness" is Part 2. "Search-set vs
held-out evaluation" and "contamination risk" are the val/test discipline of Parts 1, 3, and 6.
"Secondary metrics like context cost" is the Pareto axis from Part 4. "How noisy / how long is one
evaluation" is what set the trial count and bring-up path you just saw in Terminal-Bench 2. The
spec it produces has fixed sections mirroring the framework:

```text
# from ONBOARDING.md, lines 102–116
## Domain Summary

Explain the task, unit of evaluation, fixed components, allowed changes, base model, and optimization budget.

## Harness and Search Plan

Describe the candidate harness shape, useful baselines, what should be reusable, and what the first search loop should look like.

## Evaluation Plan

Describe the search set, held-out test set, metrics, runtime, noise, leakage risks, and any cheap validation checks.

## Experience and Logging

Describe offline traces, useful references, what should be stored from online runs, and what tooling or directory structure would make prior runs easy to inspect.
```

Filling in those four sections *is* the act of porting Meta-Harness to a new domain. Once you can
name the harness interface, a stable validation metric, a leakage-safe split, and a logging layout,
you have everything the propose→evaluate→frontier loop needs — and the two reference examples become
templates to copy from.

## What to notice

- **The interface is the only hard constraint.** "Subclass `Terminus2`" plays the same role as
  "subclass `MemorySystem`" — it's what lets one evaluator drive any candidate.
- **Domain differences are dials, not redesigns.** Pass-rate-over-trials, a smoke test, and a
  staged bring-up are responses to noise and cost; the propose/validate/benchmark/frontier skeleton
  is unchanged.
- **Onboarding is the framework as a questionnaire.** Every field in `domain_spec.md` maps to a
  concept from this series; answering them honestly is how you instantiate the loop for a new task.
- **This part is the bridge, not the destination.** Everything above is the *conceptual* map of the
  second domain: same loop, different flesh. Parts 8–11 give Terminal-Bench 2 the same per-concept
  depth text classification received in Parts 2–6.

---

*Next up: the Terminal-Bench 2 deep dive. Part 8 — The Agent Scaffold as Harness — makes the
`AgentHarness`/`Terminus2` contract concrete (the TB2 analog of Part 2), then Part 9 scores one
candidate on a real sandbox, Part 10 covers the pluggable proposer backends, and Part 11 ties the
TB2 evolution loop together and closes the series.*

## ✦ Check Your Understanding

1. In your own words, what stays constant between the text-classification and Terminal-Bench 2
   experiments, and what changes? Sort the differences into "architecture" versus "domain economics."
2. Terminal-Bench 2 adds a smoke test on top of the import check from Part 6, and attempts each task
   multiple times. Which property of the domain motivates each addition?
3. Try it: pick a task you actually care about and answer the four `domain_spec.md` section prompts
   for it. Which section is hardest to fill in — and based on Part 1, does that difficulty suggest
   Meta-Harness is a good fit or a poor one for your task?
