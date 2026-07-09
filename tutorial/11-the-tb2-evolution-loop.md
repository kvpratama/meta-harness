# Part 11 — The TB2 Evolution Loop (and the Finale)

Parts 8–10 built up the pieces: the agent scaffold as harness (Part 8), scoring one candidate on a
real sandbox (Part 9), and the pluggable proposer backends (Part 10). This part is where they run in
sequence — the TB2 counterpart of Parts 4 and 6 combined. If you followed the text-classification
outer loop, you already know the shape; here you'll see it with terminal-agent dials. It's also
where the series ends.

## The shape of a run

```diagram
   Phase 0: benchmark baselines (kira, terminus2) ─► seed frontier_val.json
        │
        ▼
   Phase 1..N (each iteration):
        propose ─► validate ─► smoke ─► benchmark ─► update frontier ─► append history
        (Part10)  (import OK) (1 task)  (Part 9)     (best per task)   (what worked)
            ▲                                                              │
            └──────────── history feeds the next propose ─────────────────┘
        │
        ▼
   Phase Final (optional): 5-trial eval of the best agent on the full dataset
```

Compare that to the text-classification diagram in Part 6: the boxes are the same. The only new box
is **smoke** — the runtime gate from Part 9 — and the metric flowing through them is pass-rate rather
than accuracy.

## Isolated run state

Every run gets its own directory tree, so concurrent or repeated runs never collide. `run_evolve`
rebinds the state-file globals under a run name at startup:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 561–573
def run_evolve(args):
    global JOBS_DIR, LOGS_DIR, PENDING_EVAL, FRONTIER_VAL, EVOLUTION_SUMMARY

    # Isolate run outputs under run-name subdirs
    if args.run_name:
        run_name = args.run_name
    else:
        run_name = datetime.now().strftime("%Y%m%d_%H%M%S")
    JOBS_DIR = EVOLVE_DIR / "jobs" / run_name
    LOGS_DIR = EVOLVE_DIR / "logs" / run_name
    PENDING_EVAL = LOGS_DIR / "pending_eval.json"
    FRONTIER_VAL = LOGS_DIR / "frontier_val.json"
    EVOLUTION_SUMMARY = LOGS_DIR / "evolution_summary.jsonl"
```

Those four files are the loop's entire persistent state, the direct analogs of the
text-classification `frontier_val.json`/`evolution_summary.jsonl`: `pending_eval.json` (the
proposer's handoff), `frontier_val.json` (best so far), `evolution_summary.jsonl` (the history), and
the `jobs/` tree (raw Harbor results). A `--fresh` run calls `fresh_start()` (line 536) to wipe the
generated candidates and logs while keeping the two baselines.

## Phase 0: establish the floor

As in Part 6, the loop first benchmarks the hand-written baselines so every candidate has something
to beat:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 587–592
    # ── Phase 0: Baselines ─────────────────────────────────────
    baseline_dirs = {}
    if not args.skip_baseline:
        print(
            f"\n{_ts()} {_bold('Phase 0: Baselines')}  agents={len(BASELINES)}  trials={args.trials}"
        )
```

The two baselines from Part 8 — `kira-baseline` and `terminus2-baseline` — get scored and seeded
into the frontier. Cached baseline runs are reused unless the model or trial count changed, the same
"a result on disk means skip" caching philosophy from Part 4.

## Phases 1..N: propose → validate → smoke → benchmark

The evolution phase resumes from the highest iteration already recorded — exactly Part 6's resume
logic, using the TB2 helper:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 661–662
    # ── Phase 1..N: Evolution ──────────────────────────────────
    start_iteration = count_iterations() + 1
```

Each iteration renders a task prompt, then calls the pluggable proposer from Part 10; a missing
`pending_eval.json` skips the round:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 685–692
        ok = propose(
            task_prompt,
            iteration,
            backend=args.proposer,
            model=args.proposer_model,
            effort=args.proposer_effort,
            timeout=args.propose_timeout,
        )
```

Then the two-stage gate from Part 9: import check, then smoke test. Only candidates that pass both
reach the expensive benchmark:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 721–729
            if validate_candidate(name, import_path):
                if args.skip_smoke:
                    print(f"{prefix} {_green('import OK')} (smoke skipped)")
                    valid.append(c)
                elif smoke_test(name, import_path):
                    print(f"{prefix} {_green('import OK + smoke OK')}")
                    valid.append(c)
                else:
                    print(f"{prefix} {_red('smoke FAIL')}")
```

Survivors are benchmarked with `harbor_run` (Part 9), each producing a per-task pass rate and a
cost/turn summary:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 762–767
            job_dir, job_result = harbor_run(
                import_path,
                job_name,
                n_trials=args.trials,
                n_concurrent=args.concurrent,
            )
```

## The frontier and the feedback channel

After benchmarking, the frontier is updated — TB2 keeps the **best agent per task** plus an overall
best, a per-task version of the Pareto idea from Part 4:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 356–366
    for agent_name, (per_task, avg) in candidates_results.items():
        for task, rate in per_task.items():
            current_best = frontier.get(task, {}).get("pass_rate", -1)
            if rate > current_best:
                frontier[task] = {
                    "best_agent": agent_name,
                    "pass_rate": rate,
                }

        current_best_avg = frontier.get("_best", {}).get("avg_pass_rate", -1)
        if avg > current_best_avg:
```

Then, exactly as in Part 6, one history row per candidate is appended — the hypothesis, the achieved
pass rate, the delta versus best, and the rollout metrics:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 830–838
        update_frontier(results, metrics=all_metrics)
        update_evolution_summary(
            iteration,
            valid,
            results,
            propose_time=propose_time,
            bench_time=bench_time,
            metrics=all_metrics,
        )
```

That `evolution_summary.jsonl` is the memory of the search. The proposer's task prompt points it
straight at these files — so each round reads what worked before it proposes:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 528–532
        f"All logs and results for this run are under `{LOGS_DIR}/`.\n"
        f"- `{LOGS_DIR / 'evolution_summary.jsonl'}` — past results\n"
        f"- `{LOGS_DIR / 'frontier_val.json'}` — frontier\n"
        f"- `{LOGS_DIR / 'reports'}/` — post-eval reports\n"
        f"- Write pending_eval.json to: `{PENDING_EVAL}`"
```

The round-trip — loop *writes* history here, proposer *reads* it there — is what makes this search
rather than random sampling, the identical mechanism from Part 6.

## Phase Final: the winner's confirmation run

Text classification touched the *test set* once at the end. TB2's final phase is a **confidence**
pass instead: because scoring is noisy, the best discovered agent is optionally re-run at a higher
trial count (5) to sharpen its pass-rate estimate:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 853–860
    # ── Phase Final: Winners get 5-trial eval on the full dataset ────────────
    if _interrupted or not args.full_eval:
        return

    print(f"\n{_ts()} {_bold('Phase Final: 5-trial eval for frontier agents')}")
    frontier = json.loads(FRONTIER_VAL.read_text()) if FRONTIER_VAL.exists() else {}
    best_agent = frontier.get("_best", {}).get("agent")
    if best_agent and best_agent != BASELINE_AGENT_NAME:
```

Same structural slot as Part 6's test pass — a single, deliberate end-of-run evaluation — but the
domain's enemy is *variance*, not leakage, so the fix is more trials rather than a hidden split.

## The CLI

`main` exposes the dials, all mapping onto concepts from the series — `--iterations` (Part 6),
`--trials` (Part 9's noise), `--proposer` backend (Part 10), and the optional winner pass:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 943–947
    parser.add_argument(
        "--full-eval",
        action="store_true",
        help="Run the optional 5-trial winner eval on the full dataset",
    )
```

## The loop is the same; only the dials moved

Put the two domains side by side and the outer loop is structurally identical — the deep dive of
Parts 8–11 has simply filled in the right column that Part 7 sketched:

```diagram
   text_classification              terminal_bench_2
   ───────────────────              ────────────────
   harness = MemorySystem           harness = AgentHarness (subclass Terminus2)
   metric  = accuracy               metric  = pass rate over N trials
   gate    = import check           gate    = import check + smoke task
   2nd axis= context length         2nd axis= tokens / turns / cost
   proposer= claude_wrapper         proposer= claude OR opencode (AgentRunner)
   final   = test set, once         final   = 5-trial winner confirmation
   ─────────────  SAME LOOP: propose → validate → benchmark → frontier → history
```

## What to notice

- **Same six-phase skeleton as Part 6.** Baselines → propose → validate → benchmark → frontier →
  history, plus the smoke gate from Part 9. Nothing about the *control flow* is new.
- **Four files are the whole state.** `pending_eval.json`, `frontier_val.json`,
  `evolution_summary.jsonl`, and `jobs/` — isolated per run — carry everything between phases and
  iterations.
- **History closes the loop.** The proposer is pointed at `evolution_summary.jsonl`; that read/write
  round-trip is what turns rounds into search, exactly as in Part 6.
- **The final phase fights the domain's enemy.** Text classification hides test to fight leakage;
  TB2 adds trials to fight variance. Same slot, different threat.

---

*That's the series. You've followed a single candidate from interface to score in two very different
domains: a `MemorySystem` scored by accuracy, and an `AgentHarness` scaffold scored by pass rate on a
real sandbox. Across both, the same loop held — propose, validate, benchmark, update a frontier, feed
history back — proving the framework never depended on the example. The natural next step: open
[ONBOARDING.md](../ONBOARDING.md), run it against a task of your own, and let it draft your
`domain_spec.md`. You now have two complete reference examples to copy from.*

## ✦ Check Your Understanding

1. Lay the TB2 loop next to the text-classification loop from Part 6. Name every phase that appears
   in both, then name the one phase TB2 adds and explain which domain property (from Part 9) forces
   it.
2. Text classification's final phase reads the held-out test set once; TB2's final phase re-runs the
   winner at 5 trials. Both occupy the same slot in the loop — what different failure mode is each
   one guarding against, and why does each domain need the guard it has?
3. Try it: you've been handed a brand-new domain. Using the side-by-side table, write the equivalent
   right-hand column for *your* task — its harness interface, metric, gates, secondary axis, proposer,
   and final phase. Which cell is hardest to fill in, and (recalling Part 1) what does that
   difficulty tell you about whether Meta-Harness fits?
