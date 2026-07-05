# Part 4 — Scoring Many: the Sweep and the Frontier

The inner loop scores *one* harness on *one* dataset. But a search round produces several candidates,
and each must be tried on every dataset (sometimes across several seeds). [benchmark.py](../reference_examples/text_classification/benchmark.py)
is the orchestration layer that turns that grid into concurrent jobs, collects the results, and
ranks them. Think of it as the bridge between "evaluate a harness" (Part 3) and "search for better
harnesses" (Part 6).

## Discover candidates from disk

The proposer (Part 5) writes new candidate `.py` files into `agents/`. The benchmark doesn't need a
registry of them — it just scans the directory:

```python
# from reference_examples/text_classification/benchmark.py, lines 44–52
def discover_all_memory_systems() -> list[tuple[str, str]]:
    """Auto-discover all memory system .py files on disk."""
    base = Path(__file__).parent
    systems = []
    for f in sorted((base / "agents").glob("*.py")):
        name = f.stem
        if name in _SKIP_MEMORY_FILES:
            continue
        systems.append((name, f"agents/{name}.py"))
```

This auto-discovery is what makes the search open-ended: a candidate exists the moment its file
exists. There's no config to edit, no list to append to — drop a valid `MemorySystem` subclass into
`agents/` and the next sweep picks it up.

## A grid of jobs, run concurrently

A sweep is the cross product **datasets × memory systems × seeds**. Each cell becomes one
subprocess invocation of the inner loop from Part 3. Crucially, each cell writes to a deterministic
directory, and an existing result means "skip this cell":

```python
# from reference_examples/text_classification/benchmark.py, lines 144–153
def run_dir(
    base: Path, dataset: str, memory: str, model: str, seed: int = DEFAULT_SEED
) -> Path:
    """Construct hierarchical run directory path.

    logs/{dataset}/{memory}/{model}/          (default seed)
    logs/{dataset}/{memory}/{model}_seed{N}/  (non-default seed)
    """
    leaf = model if seed == DEFAULT_SEED else f"{model}_seed{seed}"
    return base / dataset / memory / leaf
```

That layout is the whole caching strategy. Because the path is a pure function of
`(dataset, memory, model, seed)`, a sweep is **resumable**: if `val.json` already sits in a cell's
directory, the work is done and the job is skipped. Crash halfway through 30 jobs, rerun, and only
the missing cells execute. The jobs themselves run under an `asyncio` semaphore so many evaluate at
once without overwhelming the model endpoint.

```diagram
   datasets  ×  memory systems  ×  seeds
        │            │              │
        └────────────┴──────────────┘
                     │  one cell = one inner-loop subprocess
                     ▼
   logs/<dataset>/<memory>/<model>/val.json   ◄── exists? skip. missing? run.
                     │
                     ▼
   load_results()  ──►  {(model, dataset, memory): {accuracy, ctx_len, ...}}
```

## Reading results back

After the grid runs, results are read straight off the filesystem by globbing for the result files
and reconstructing the key from each path:

```python
# from reference_examples/text_classification/benchmark.py, lines 176–193
def load_results(base_dir: Path, filename: str = "val.json") -> dict:
    """Load results from hierarchical dir structure.

    Globs base_dir/**/filename, parses path to extract (dataset, memory, model, seed).
    Returns dict: (model, dataset, memory) -> data dict (with 'accuracy' field).
    """
    results = {}
    for filepath in base_dir.rglob(filename):
        parsed = parse_run_path(base_dir, filepath)
        if not parsed:
            continue
        try:
            data = json.loads(filepath.read_text())
            key = (parsed["model"], parsed["dataset"], parsed["memory"])
            results[key] = data
        except (json.JSONDecodeError, KeyError):
            continue
    return results
```

The directory *is* the database. There's no separate index to keep in sync — the path encodes the
key, and one corrupt or missing file simply drops out of the results instead of crashing the run.
Note the default filename is `val.json`; the test results live under a different name in a separate
tree, which is how the "test never exposed during search" rule from Part 1 is physically enforced.

## The Pareto frontier: accuracy is not the only axis

A harness that's 1% more accurate but stuffs 200,000 characters into every prompt may not be a
better harness. So the benchmark ranks candidates on **two** axes at once — maximize accuracy,
minimize injected context (the `get_context_length` from Part 2):

```python
# from reference_examples/text_classification/benchmark.py, lines 228–244
def compute_pareto_frontier(
    points: list[tuple[str, float, int]],
) -> list[tuple[str, float, int]]:
    """Compute Pareto frontier for (name, accuracy, ctx_tokens).

    A point is Pareto-optimal if no other point has both
    higher accuracy AND lower ctx_tokens (maximize accuracy, minimize tokens).
    Returns points sorted by accuracy descending.
    """
    sorted_points = sorted(points, key=lambda x: (-x[1], x[2]))
    pareto = []
    min_tokens = float("inf")
    for name, acc, tok in sorted_points:
        if tok <= min_tokens:
            pareto.append((name, acc, tok))
            min_tokens = tok
    return pareto
```

A point survives only if nothing else is both more accurate *and* cheaper. The output isn't a
single winner but a **set** of non-dominated harnesses — a cheap-but-decent one, an
expensive-but-best one, and trade-offs in between. The frontier this produces (written to
`frontier_val.json`) is exactly the state the outer loop carries forward and shows the proposer next
round, which is where Part 6 picks up.

## What to notice

- **Files are the registry and the cache.** Candidates are discovered by globbing `agents/`;
  finished work is detected by an existing `val.json`. No central state to maintain.
- **The path encodes the key.** `run_dir` makes results addressable and sweeps resumable; a crash
  costs you only the unfinished cells.
- **Validation and test are physically separated.** `load_results` defaults to `val.json`; test
  lives elsewhere, so search literally cannot read the held-out set.
- **Two objectives, not one.** The Pareto frontier keeps the whole accuracy-vs-cost trade-off curve,
  so the search optimizes for efficient harnesses, not just maximally accurate ones.

---

*Next up: Part 5 — The Proposer — how an LLM coding agent is run as a subprocess with a SKILL document as its prior, and how that document keeps it from producing trivial parameter tweaks.*

## ✦ Check Your Understanding

1. Explain why encoding the run key into the directory path (rather than, say, a database row) makes
   the sweep both resumable and self-caching. What single fact does the presence of `val.json` tell
   the orchestrator?
2. You add a new candidate that scores 62% with 180k chars of context, while an existing one scores
   61% with 5k chars. Walk through `compute_pareto_frontier`: do both survive, and what does that say
   about how the search treats "best"?
3. Try it: where would you change the call to `load_results` to inspect *test* results instead of
   validation, and why does the framework make you go out of your way to do that?
