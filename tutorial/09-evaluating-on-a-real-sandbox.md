# Part 9 — Evaluating on a Real Sandbox

Part 3 turned one `MemorySystem` into one accuracy number with a few model calls. TB2's inner loop
does the same job — one candidate in, one score out — but the "run" is now an agent driving a real
Linux sandbox through dozens of turns, on tasks that are *stochastic*. That single fact reshapes
everything: the metric becomes a pass rate over trials, the cheap import check grows a runtime gate,
and cost forces a staged bring-up. This part is the TB2 analog of "scoring one candidate."

## Running one candidate: `harbor_run`

The loop scores a candidate by shelling out to Harbor via a thin wrapper, exactly as text
classification shelled out to its inner loop:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 140–155
def harbor_run(import_path, job_name, n_trials=2, n_concurrent=10):
    """Run harbor eval on the paper TB2 config via runloop.

    result_dict is None if harbor crashed hard; job_dir may still have partial results.
    """
    cmd = [
        str(EVOLVE_DIR / "scripts" / "run_eval.sh"),
        import_path,
        EVAL_TASK_SET,
        str(n_trials),
        str(n_concurrent),
        "--job-name",
        job_name,
        "--jobs-dir",
        str(JOBS_DIR),
    ]
```

The actual `harbor run` invocation lives in the [run_eval.sh](../reference_examples/terminal_bench_2/scripts/run_eval.sh)
wrapper, which assembles the CLI call and points it at the runloop sandbox provider:

```bash
# from reference_examples/terminal_bench_2/scripts/run_eval.sh, lines 64–72
CMD=(
    uv run harbor run
    --agent-import-path "$AGENT_IMPORT_PATH"
    -d "terminal-bench@2.0"
    -m "$MODEL"
    -e runloop
    -n "$N_CONCURRENT"
    --n-attempts "$RUNS"
)
```

`--n-attempts "$RUNS"` is the key difference from Part 3. Each task is attempted several times
because a terminal task can pass on one run and fail on the next.

## Three task sets: smoke → hard → full

The wrapper accepts a task set and either passes task filters or lets Harbor run everything:

```bash
# from reference_examples/terminal_bench_2/scripts/run_eval.sh, lines 39–47
TASK_FLAGS=()
case "$TASK_SET" in
    hard)
        for t in "${HARD_TASKS[@]}"; do TASK_FLAGS+=(-i "$t"); done ;;
    full)
        ;;  # no task flags: harbor runs the full dataset
    *)
        echo "Unknown task_set '$TASK_SET'. Use: hard | full" >&2; exit 1 ;;
esac
```

`full` is the whole official dataset; `hard` is a hand-picked 30-task subset for cheaper development;
and a single easy task serves as a smoke probe. Those anchors are declared as constants in
`meta_harness.py`:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 94–102
EVAL_TASK_SET = "full"
N_EVAL_TASKS = 89  # full official TB2 dataset used in the paper runs

SMOKE_TEST_TASK = "extract-elf"  # simple task, reliably fast

DATASET = "terminal-bench@2.0"
MODEL = "anthropic/claude-opus-4-6"
DEFAULT_SEARCH_TRIALS = 2
DEFAULT_CONCURRENCY = 50
```

The 30-task hard subset is baked into the wrapper for fast iteration loops:

```bash
# from reference_examples/terminal_bench_2/scripts/run_eval.sh, lines 26–31
# 30-task hard subset for cheaper development and debugging loops.
HARD_TASKS=(
    bn-fit-modify cancel-async-tasks circuit-fibsqrt configure-git-webserver
    dna-assembly extract-moves-from-video feal-differential-cryptanalysis
    feal-linear-cryptanalysis fix-code-vulnerability fix-ocaml-gc
    gpt2-codegolf install-windows-3.11 llm-inference-batching-scheduler
```

## Pass rate over trials

Because tasks are stochastic, a "score" is no longer a single correct/incorrect. The loop reads
every trial directory as ground truth — a missing or corrupt result counts as a failure, matching
Harbor's own `total_passes / total_trials` metric:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 217–226
        vr = r.get("verifier_result") or {}
        reward = (vr.get("rewards") or {}).get("reward")
        task_rewards.setdefault(task, []).append(
            float(reward) if reward is not None else 0.0
        )

    # Validate trial counts
    if expected_trials:
        for task, rewards in task_rewards.items():
            if len(rewards) != expected_trials:
```

Those per-task reward lists are collapsed into pass rates, with the average deliberately computed
*flat* rather than as a mean-of-means:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 234–250
def compute_pass_rates(task_rewards):
    """Compute pass rate per task and flat average. Returns (per_task, avg).

    avg is total_passes / total_trials (flat, matching harbor's metric),
    NOT the mean of per-task rates.
    """
    per_task = {}
    total_passes = 0
    total_trials = 0
    for task, rewards in task_rewards.items():
        per_task[task] = sum(r > 0 for r in rewards) / len(rewards) if rewards else 0.0
        total_passes += sum(r > 0 for r in rewards)
        total_trials += len(rewards)

    avg = total_passes / total_trials if total_trials else 0.0
    return per_task, avg
```

This is the TB2 counterpart of Part 3's accuracy — the single number the outer loop maximizes — but
its honesty comes from *averaging over noise*, not from an answer-before-learning discipline.

## Secondary metrics: the Pareto axis, TB2-style

Part 4 optimized accuracy against injected context length. TB2 tracks a richer set of cost signals —
tokens, turns, and dollars — parsed per trial:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 275–284
        metrics = {
            "n_input_tokens": ar.get("n_input_tokens"),
            "n_output_tokens": ar.get("n_output_tokens"),
            "n_cache_tokens": ar.get("n_cache_tokens"),
            "cost_usd": ar.get("cost_usd"),
            "n_turns": md.get("n_episodes"),
            "n_api_calls": len(md.get("api_request_times_msec", [])),
            "reward": reward,
        }
        per_task.setdefault(task, []).append(metrics)
```

`summarize_trial_metrics` then aggregates those into totals and means the loop logs alongside pass
rate:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 288–289
def summarize_trial_metrics(trial_metrics):
    """Aggregate per-trial metrics into a summary dict."""
```

These are the "secondary metrics" the onboarding questionnaire (Part 7) asked about — latency,
context cost, API spend — surfaced so a slightly-worse-but-far-cheaper scaffold is legible to the
search rather than invisible.

## Two gates: import check + smoke test

Part 6 had one cheap gate before the expensive benchmark: an import check. TB2 keeps it —

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 453–462
def validate_candidate(name, import_path):
    """Import-check a candidate agent. Returns True if valid."""
    module_path = import_path.split(":")[0]
    result = run_cmd(
        ["uv", "run", "python", "-c", f"from {module_path} import *; print('OK')"],
        cwd=str(EVOLVE_DIR),
        timeout=30,
    )
    if result.returncode == 0 and "OK" in result.stdout:
        return True
```

— and adds a second gate that the text-classification loop didn't need: a **smoke test** that
actually runs the agent for one trial on one easy task. A scaffold can import cleanly yet deadlock
in its agent loop, so this catches runtime crashes before a full sweep is paid for:

```python
# from reference_examples/terminal_bench_2/meta_harness.py, lines 469–488
def smoke_test(name, import_path, timeout=1800):
    """Run 1 trial on 1 task to check for runtime crashes. Returns True if passed."""
    job_name = f"smoke-{name}"
    job_dir = JOBS_DIR / job_name
    if job_dir.exists():
        run_cmd(["rm", "-rf", str(job_dir)])

    cmd = [
        str(EVOLVE_DIR / "scripts" / "run_eval.sh"),
        import_path,
        "full",
        "1",
        "1",
        "-i",
        SMOKE_TEST_TASK,
        "--job-name",
        job_name,
        "--jobs-dir",
        str(JOBS_DIR),
    ]
```

The smoke test even inspects the result for reported errors, not just the exit code — a candidate
that runs but errors on every trial is rejected before the sweep.

```diagram
   text_classification              terminal_bench_2
   ───────────────────              ────────────────
   gate: import check (30s)         gate 1: import check (30s)
                                    gate 2: smoke test — 1 task × 1 trial (runtime)
   metric: accuracy                 metric: pass rate = total_passes / total_trials
   2nd axis: context length         2nd axis: tokens / turns / cost per trial
   ─────────────  bring-up: smoke → hard (30 tasks) → full (89 tasks)
```

## Domain economics drive the shape

Two forces from the onboarding questionnaire explain every difference here. **Noise** → each task is
run `DEFAULT_SEARCH_TRIALS` times and scored as a rate, so a lucky single pass can't inflate a
candidate. **Cost and time** → an evaluation is minutes on a real sandbox, not a few model calls, so
the loop stages bring-up: prove the candidate imports (30s), prove it runs (one smoke task), then
spend on the hard subset or the full 89-task sweep. Same inner-loop job as Part 3; the dials are set
by the physics of the domain.

## What to notice

- **A score is a pass rate, averaged over trials.** Stochastic tasks make one run untrustworthy;
  `--n-attempts` and a flat `total_passes / total_trials` average are the response.
- **Every trial dir is ground truth.** Missing, corrupt, or errored trials all count as reward 0,
  matching Harbor's own metric — no silent dropping of failures.
- **Two gates, not one.** Import check (30s) then smoke test (one real trial) protect the expensive
  sweep from candidates that import but crash at runtime.
- **Economics set the dials.** Noise picks the trial count; cost picks the staged smoke → hard →
  full bring-up. The inner-loop *job* is unchanged from Part 3.

---

*Next up: Part 10 — The Proposer Backends — the pluggable CLI agents (Claude and opencode) that write
each new candidate, the shared `AgentRunner` seams, and the one SKILL prior that steers both.*

## ✦ Check Your Understanding

1. `compute_pass_rates` computes the average as `total_passes / total_trials` rather than the mean of
   per-task rates. Construct a small example (two tasks, different trial counts) where the two
   methods disagree, and explain why the flat average matches Harbor's metric.
2. Part 6 needed only an import check; TB2 adds a smoke test. Which property of an agent scaffold —
   absent from a `MemorySystem` — makes "it imports" insufficient evidence that it's worth
   benchmarking?
3. Try it: you have 20 candidates and a fixed compute budget. Using the smoke → hard → full staging,
   sketch how you'd spend the budget, and explain what each stage is buying you in terms of noise vs
   cost.
