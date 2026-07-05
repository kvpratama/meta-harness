# Part 3 — Scoring One Candidate: the Inner Loop

The outer loop is only as trustworthy as the number it optimizes. That number comes from the
**inner loop**: given one harness and one dataset, run the harness over the examples, compare each
prediction to ground truth, and return an accuracy. This is where the `predict`/`learn_from_batch`
contract from Part 2 actually gets exercised — and where the "answer before learning" discipline
is enforced.

## Online mode: predict, then learn

The default mode is *online*. For each batch, the loop runs every `predict` first (blind to the
answer), scores the results, and only then calls `learn_from_batch`:

```python
# from reference_examples/text_classification/inner_loop.py, lines 332–354
    for batch_start in range(0, len(examples), batch_size):
        batch = examples[batch_start : batch_start + batch_size]

        # PHASE 1: PREDICT (parallel within batch)
        if batch_size == 1:
            pred_results = [predict_one(0, batch[0])]
        else:
            pred_results = []
            with ThreadPoolExecutor(max_workers=min(max_workers, len(batch))) as exe:
                futures = {
                    exe.submit(predict_one, i, ex): i for i, ex in enumerate(batch)
                }
                for future in as_completed(futures):
                    pred_results.append(future.result())
            pred_results.sort(key=lambda x: x[0])

        # Build batch_results for learn_from_batch
        batch_results = []
        for idx, ex, pred, meta, prompt_info, _predict_s in pred_results:
            global_idx = step_offset + batch_start + idx
            inp, tgt = ex["input"], ex["target"]
            raw = check_answer(pred, tgt, **_get_eval_kwargs(ex))
            ok, metrics = _unpack_eval_result(raw)
            correct += int(ok)
```

The two-phase structure is explicit in the comments: **PHASE 1: PREDICT**, then scoring, then —
once the batch is fully predicted — the learning step:

```python
# from reference_examples/text_classification/inner_loop.py, lines 398–400
        # PHASE 2: LEARN FROM BATCH
        t0 = time.time()
        memory.learn_from_batch(batch_results)
```

This is the contract from Part 2 enforced at the loop level. Within a batch, no `predict` call can
benefit from the truth of any example in that same batch — predictions are committed first, and the
`batch_results` handed to `learn_from_batch` carry the real answers in `ground_truth`. Smaller
batches mean the harness learns more often (fully online at `batch_size=1`); larger batches mean
more predictions happen before any update.

## Offline mode: learn with answers, then evaluate

Some harnesses don't want a streaming, predict-first regimen — they want to *study* a labeled
training set, then be tested. That's *offline* mode, dispatched at the top of the same function:

```python
# from reference_examples/text_classification/inner_loop.py, lines 308–318
    if mode == "offline":
        return _run_offline_loop(
            memory=memory,
            examples=examples,
            check_answer=check_answer,
            num_epochs=num_epochs,
            batch_size=batch_size,
            max_workers=max_workers,
            logger=logger,
            step_offset=step_offset,
            collect_trajectory=collect_trajectory,
```

In offline mode the training phase hands the *ground truth itself* to `learn_from_batch` as the
"prediction," so the harness learns from correct answers directly:

```python
# from reference_examples/text_classification/inner_loop.py, lines 145–153
            # Create batch_results with ground truth as "prediction"
            batch_results = []
            for ex in batch:
                r = {
                    "input": ex["input"],
                    "prediction": ex["target"],  # Ground truth visible
                    "ground_truth": ex["target"],
                    "was_correct": True,
                }
```

The crucial discipline: even though training sees labels, **accuracy is always measured afterward
on a separate prediction pass with no updates.** Studying the answer key is allowed; grading
yourself on the answer key is not.

```diagram
   online                                offline
   ─────────                             ─────────
   for each batch:                       train phase (labels visible):
     predict (blind) ──► score             learn_from_batch(truth) × epochs
            │                              eval phase (no updates):
            ▼                                predict (blind) ──► score
     learn_from_batch(truth)
   one pass, learns as it goes           study first, then a clean exam
```

## The evaluator contract

How does the loop decide a prediction is "correct"? It calls a `check_answer` function — a
per-dataset *evaluator* — and normalizes whatever it returns:

```python
# from reference_examples/text_classification/inner_loop.py, lines 51–60
def _unpack_eval_result(raw) -> tuple[bool, dict]:
    """Normalize evaluator output to (ok, metrics).

    Evaluators return either:
    - bool: simple correct/incorrect
    - dict: {"was_correct": bool, "metrics": {...}}
    """
    if isinstance(raw, dict):
        return raw["was_correct"], raw.get("metrics", {})
    return bool(raw), {}
```

An evaluator can return a plain `bool` for exact-match tasks or a `dict` carrying extra metrics
(like the per-charge precision/recall used for the multi-label LawBench task). A representative one
parses the model's free-form reply down to a normalized label before comparing:

```python
# from reference_examples/text_classification/data/evaluators.py, lines 79–96
def eval_symptom2disease(prediction: str, target: str) -> bool:
    text = extract_final_answer(prediction)
    match = re.search(r"\[DIAGNOSIS\](.*?)\[/DIAGNOSIS\]", text, re.I | re.S)
    if match:
        text = match.group(1).strip()
    else:
        match = re.search(
            r"(?:diagnosis|final diagnosis|conclusion)[:：]\s*([^\n]+)", text, re.I
        )
        if match:
            text = match.group(1).strip()

    def normalize(value: str) -> str:
        value = value.lower().strip()
        value = re.sub(r"\s+", " ", value)
        return re.sub(r"[.!?]+$", "", value)

    return normalize(text) == normalize(target)
```

The evaluator is the "real success metric" Part 1 insisted on. It is deliberately tolerant of
formatting noise (tags, casing, punctuation) so the score reflects whether the harness got the
*answer* right, not whether it matched a string exactly.

## What to notice

- **Two phases, never interleaved.** Predict the whole batch, score it, *then* learn. This is the
  Part 2 contract enforced one level up.
- **Online vs offline is a knob, not two systems.** Same entry function; offline just lets the
  harness study labels first, but always grades on a clean, update-free pass.
- **`check_answer` is pluggable.** Returning `bool` or `dict` lets simple and metric-rich tasks
  share one loop, and parsing-tolerant evaluators keep the score about substance, not formatting.
- **This number is the search signal.** Everything the outer loop does is in service of maximizing
  what this function returns — on validation data, never test (Part 1's leakage rule, made concrete
  next in Part 4).

---

*Next up: Part 4 — Scoring Many — how `benchmark.py` turns candidates × datasets × seeds into concurrent jobs, stores results in a hierarchical layout, and computes the accuracy-vs-context Pareto frontier.*

## ✦ Check Your Understanding

1. In your own words, contrast online and offline mode. For a memory system that benefits from
   seeing the same examples several times, which mode (and which parameter) would you reach for?
2. Offline training sets `"prediction": ex["target"]` and `"was_correct": True`. Why is it safe for
   the *training* phase to feed the harness perfect answers, given how the final accuracy is
   measured?
3. Try it: `eval_symptom2disease` returns a `bool`. Sketch how you'd change it to instead return the
   `dict` form from `_unpack_eval_result`, adding a confidence-style metric — and confirm the inner
   loop would need no changes to consume it.
