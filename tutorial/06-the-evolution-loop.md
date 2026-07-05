# Part 6 — Tying It Together: the Evolution Loop

You've now seen every component: the harness contract (Part 2), the inner loop that scores one
candidate (Part 3), the sweep and frontier that score many (Part 4), and the proposer that writes
new ones (Part 5). The outer loop in [meta_harness.py](../reference_examples/text_classification/meta_harness.py)
is the conductor that runs them in sequence, iteration after iteration. This part is about the
*control flow* — the order of operations and the feedback channel that turns a sequence of rounds
into actual search.

## The shape of a run

```diagram
   Phase 0: benchmark the baselines ─► seed frontier_val.json
        │
        ▼
   Phase 1..N (each iteration):
        propose  ─► validate ─► benchmark ─► update frontier ─► append history
        (Part 5)   (import OK)  (Part 4)     (best so far)      (what worked)
            ▲                                                       │
            └───────────── history feeds the next propose ─────────┘
        │
        ▼
   Phase Final: run the frontier systems on the TEST set (once, at the very end)
```

## Phase 0: establish the floor

Before searching, the loop benchmarks the hand-written baselines so there's something to beat:

```python
# from reference_examples/text_classification/meta_harness.py, lines 309–312
    # ── Phase 0: Baselines ─────────────────────────────────────
    baselines = cfg["memory_systems"]["baselines"]
    if not args.skip_baseline:
        print(f"\n{_ts()} {_bold('Phase 0: Baselines')}  systems={baselines}")
```

`NoMemory` and `FewShotAll` (Part 2) get scored and seeded into the frontier. Every candidate the
proposer later invents is measured against this starting line.

## Phases 1..N: propose → validate → benchmark → record

The evolution phase is a loop, and the first thing it does is figure out where to resume from —
the highest iteration already recorded in the history file:

```python
# from reference_examples/text_classification/meta_harness.py, lines 340–347
    # ── Phase 1..N: Evolution ──────────────────────────────────
    start_iteration = count_iterations_from_summary() + 1
    for i in range(args.iterations):
        if _interrupted:
            print("Interrupted.")
            break

        iteration = start_iteration + i
```

Each iteration first calls the proposer from Part 5, treating an absent `pending_eval.json` as a
failed round to skip:

```python
# from reference_examples/text_classification/meta_harness.py, lines 367–377
        # Propose
        propose_start = time.time()
        print(f"  {_ts()} {_cyan('proposing')} new candidates...", flush=True)
        ok = propose_claude(task_prompt, iteration, timeout=args.propose_timeout)
        propose_time = time.time() - propose_start

        if not ok:
            print(
                f"  {_red('FAIL')} proposer returned no candidates after {_elapsed(propose_time)}"
            )
            continue
```

Then comes a cheap gate before paying for any evaluation. The proposer is an LLM; it can write code
that doesn't import. So every candidate is import-checked first, and broken ones are dropped:

```python
# from reference_examples/text_classification/meta_harness.py, lines 179–197
def validate_candidates(candidates):
    """Import-check each candidate. Returns list of valid candidates."""
    valid = []
    for c in candidates:
        name = c["name"]
        result = run_cmd(
            [
                "uv",
                "run",
                "python",
                "-c",
                f"from text_classification.agents.{name} import *; print('OK')",
            ],
            cwd=str(EVOLVE_DIR.parent),
            timeout=30,
        )
        if result.returncode == 0 and "OK" in result.stdout:
            print(f"    {_green('OK')} {name}")
            valid.append(c)
```

This ordering — a 30-second import check before a multi-minute benchmark — is a deliberate cost
gate. Only survivors are handed to the Part 4 sweep, after which the frontier is recomputed.

## The feedback channel: `evolution_summary.jsonl`

This is the line that makes it *search* rather than *random sampling*. After benchmarking, the loop
appends one row per candidate — the hypothesis, the achieved score, and the delta versus the best so
far:

```python
# from reference_examples/text_classification/meta_harness.py, lines 218–231
    with open(EVOLUTION_SUMMARY, "a") as f:
        for i, c in enumerate(candidates):
            name = c["name"]
            avg_val = val_scores.get(name, 0)
            row = {
                "iteration": iteration,
                "system": name,
                "avg_val": round(avg_val, 1),
                "axis": c.get("axis", "?"),
                "hypothesis": c.get("hypothesis", ""),
                "delta": round(avg_val - best_val, 1) if best_val else None,
                "outcome": f"{avg_val:.1f}% ({avg_val - best_val:+.1f})"
                if avg_val > 0
                else "failed",
            }
```

Recall from Part 5 that the proposer's task prompt points it at this very file. So the loop closes:
the proposer reads `evolution_summary.jsonl` to see which hypotheses paid off and which flopped,
avoids re-treading dead ends, and builds on winners. **The history is the memory of the search.**
Each candidate's stored `hypothesis` and `delta` is what lets the next round reason about cause and
effect rather than guessing afresh.

## Phase Final: touch the test set, once

Throughout every iteration, scoring used *validation* data only (Parts 1, 3, 4). The held-out test
set is read exactly once, at the very end, and only for the systems that made the frontier:

```python
# from reference_examples/text_classification/meta_harness.py, lines 476–490
    frontier = json.loads(FRONTIER_VAL.read_text()) if FRONTIER_VAL.exists() else {}
    pareto = frontier.get("_pareto", [])

    test_systems = set(baselines)
    for entry in pareto:
        test_systems.add(entry["system"])
    for key, val in frontier.items():
        if not key.startswith("_") and isinstance(val, dict) and "best_system" in val:
            test_systems.add(val["best_system"])

    for name in sorted(test_systems):
        print(f"  {_ts()} test eval: {_bold(name)}", flush=True)
        result = run_benchmark(["--memory", name, "--test"])
```

This is the payoff of the "val-only during evolution" rule from Part 1. Because the search never
optimized against test, the final test numbers are an honest estimate of how the discovered
harnesses generalize — not a figure the search was secretly chasing.

## What to notice

- **Phase 0 sets the bar.** Baselines are scored first so every later candidate has a meaningful
  delta to report.
- **Validate before you benchmark.** A 30-second import check protects the expensive evaluation step
  from the proposer's inevitable syntax slips.
- **The history file is the optimizer's state.** `evolution_summary.jsonl` is written here and read
  by the proposer there; that round-trip is what makes successive rounds *improve*.
- **Test is touched once, at the end, on frontier systems only.** The whole architecture exists to
  keep that number trustworthy.

---

*Next up: Part 7 — Generalizing to a New Domain — the same propose/evaluate/frontier loop applied to terminal-agent scaffolds, and how ONBOARDING.md turns any new domain into a spec.*

## ✦ Check Your Understanding

1. In your own words, what makes this loop a *search* rather than just generating-and-testing random
   candidates? Point to the specific file that carries information between iterations.
2. Why does the loop run a 30-second import check before benchmarking, and why is `continue`
   (skipping the iteration) the right response to a proposer that produced no `pending_eval.json`?
3. Try it: trace what would happen to the final test numbers if a bug caused the validation sweep to
   accidentally read test data during evolution. Which property from Part 1 would be violated, and
   why would the reported result become meaningless?
