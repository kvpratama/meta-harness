# Part 1 — The Big Idea: Searching Over Harnesses

> **About this series.** These seven parts teach the Meta-Harness framework to developers who
> already know Python but are new to this repo. We use the `text_classification` reference
> experiment as the running example and bring in `terminal_bench_2` at the end to show the
> pattern generalizes. Every code snippet cites a file path and line numbers; those line numbers
> are tied to the repo snapshot at commit `95175f7`. If the code has moved since, the surrounding
> function names will still get you to the right place.

You have a fixed model — say `gpt-oss-120b` or Claude Opus — and a task it doesn't ace. The usual
instinct is to reach for a better model or fine-tune the one you have. Meta-Harness makes a
different bet: **leave the model frozen and improve the code around it.**

That surrounding code has a name here.

```python
# from README.md, line 5
Meta-Harness is a framework for automated search over task-specific model harnesses: the code around a fixed base model that decides what to store, retrieve, and show while the model works.
```

A *harness* is everything that isn't the model: what context you retrieve, what you remember
between examples, how you format the prompt, what tools you expose, how you parse the reply. The
claim is that for many tasks, the harness — not the model — is where the easy wins are hiding.

## Why search, and why automate it

Hand-tuning a harness is slow and biased toward whatever you thought of first. Meta-Harness turns
harness design into a **search problem** and hands the search to an LLM coding agent. You define
the rules of the game; the framework plays many rounds.

The framework is most worth using when a few things are true:

```text
# from ONBOARDING.md, lines 30–33
- The task is long-horizon or multi-step, so harness choices matter.
- There are repeated tasks or episodes, not just one-off bespoke workflows.
- The base model is fixed, and the main opportunity is better retrieval, memory, context construction, planning, or tool-use scaffolding.
- There is a measurable evaluation loop with a real success metric, and prior evidence points towards significant gain from changing the harness.
```

The thread running through all four: there must be a **stable, measurable evaluation loop**.
Search is only as good as the score it optimizes. No reliable metric, no Meta-Harness.

## The two loops

The whole system is two nested loops, and almost everything in this repo is one or the other.

```text
OUTER LOOP  — searches for better harnesses
  repeat each iteration:
    1. a proposer agent writes a few new candidate harnesses (Python files)
    2. the INNER LOOP scores each candidate on a validation set
    3. results update a "frontier" of the best harnesses so far
    4. that history is fed back to the proposer next iteration

INNER LOOP  — measures one harness
    run the harness over the data, compare predictions to ground truth,
    return an accuracy number
```

You can read that structure straight off the outer loop's own docstring:

```python
# from reference_examples/text_classification/meta_harness.py, lines 1–4
"""Autonomous evolution loop for memory systems.

Val-only during evolution (test never exposed).
Uses claude_wrapper + meta-harness skill to propose new memory systems.
```

Three phrases there preview the rest of the series. *"Evolution loop"* is the outer loop (Part 6).
*"Val-only during evolution (test never exposed)"* is the leakage discipline baked into scoring
(Part 3) — the held-out test set is never shown while the search is running, so a high score can't
be an artifact of overfitting to the thing you'll report on. *"claude_wrapper + meta-harness
skill to propose"* is the proposer (Part 5): an LLM agent, steered by a skill document, that writes
the candidate code.

## What to notice

- **The model is a constant, not a variable.** Everything Meta-Harness changes lives outside the
  model call. Keep that boundary in mind — it's what makes the search tractable.
- **A candidate harness is just a Python file** that satisfies a fixed interface. The search space
  is "programs that implement that interface." Part 2 makes the interface concrete.
- **Two loops, two jobs.** The inner loop answers *"how good is this one harness?"*; the outer loop
  answers *"can we find a better one?"* Almost every file in the repo belongs to one of them.

## Where this series goes

We'll follow the data path of a single candidate from the inside out: the contract a harness must
satisfy (Part 2), how one candidate is scored (Part 3), how many are scored at once (Part 4), how
new ones get written (Part 5), and how the outer loop ties it together (Part 6). Part 7 swaps the
domain entirely — from text-classification memory systems to terminal-agent scaffolds — to show the
framework didn't depend on the example.

---

*Next up: Part 2 — The Harness Contract — the exact five-method interface every candidate must implement, and the two baselines that show the minimum and the maximum.*

## ✦ Check Your Understanding

1. In your own words, what is the difference between "the model" and "the harness" in
   Meta-Harness? Name two concrete things that belong to the harness.
2. Suppose a colleague wants to use Meta-Harness to make a brainstorming chatbot "feel smarter" in
   open-ended conversation. Based on the conditions in this part, which property is missing, and
   where in the loop would that absence cause trouble?
3. The outer loop's docstring says evaluation is "val-only ... test never exposed." Before reading
   Part 3, predict *why* the framework would go out of its way to hide the test set during search.
