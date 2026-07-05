# Text Classification (opencode proposer)

Text classification reference experiment for Meta-Harness. This variant adds
**opencode** as a proposer backend alongside Claude Code; both are supported and
the backend is selectable in [`config.yaml`](config.yaml) (opencode is the
default here). The outer loop ([`meta_harness.py`](meta_harness.py)) drives the
selected agentic CLI to write candidate memory systems into `agents/`; the inner
loop ([`inner_loop.py`](inner_loop.py)) evaluates them on the datasets in
`config.yaml`.

This is a faithful port of the Claude Code reference from the upstream
[Meta-Harness](https://github.com/stanford-iris-lab/meta-harness) repo
(`reference_examples/text_classification`): the harness, inner loop, memory
system, and datasets are identical. The only addition is the second proposer
backend (opencode). Backend-agnostic
plumbing lives in [`agent_runner.py`](agent_runner.py), with thin subclasses in
[`claude_wrapper.py`](claude_wrapper.py) and
[`opencode_wrapper.py`](opencode_wrapper.py).

## Quick Start

Install Python deps:

```bash
cd reference_examples/text_classification
uv sync
```

Install and authenticate the proposer CLI (only needed for `--iterations >= 1`):

- **opencode** (default backend): install per the
  [opencode docs](https://opencode.ai), then `opencode auth login`. List valid
  `provider/model` identifiers with `opencode models`.
- **claude** (alternate backend): install Claude Code and sign in; the harness
  uses your Claude subscription auth.

Run one evolve iteration (uses the proposer backend from `config.yaml`):

```bash
uv run python meta_harness.py --iterations 1
```

Run evaluation of a previous run's candidates (baselines set in `config.yaml`)
without proposing anything new:

```bash
uv run python meta_harness.py --iterations 0 --run-name <run-name>
```

Continue evolution for 2 more iterations from an existing run, skipping baseline
eval:

```bash
uv run python meta_harness.py --iterations 2 --run-name <run-name> --skip-baseline
```

Override the proposer backend on the command line:

```bash
uv run python meta_harness.py --iterations 1 --proposer claude
```

Run one memory system on one dataset (single-candidate inner-loop eval):

```bash
PYTHONPATH=.. uv run python -m text_classification.inner_loop \
  --memory fewshot_all \
  --dataset USPTO2
```

Print the benchmark summary:

```bash
uv run python benchmark.py --results
```

Run benchmark on no_memory MemorySystem:
```bash
uv run python benchmark.py --logs-dir /home/openclaw/meta-harness/reference_examples/text_classification/logs/20260626_175943 --memory no_memory
```

## Proposer Configuration

The proposer is configured under `proposer:` in [`config.yaml`](config.yaml):

```yaml
proposer:
  backend: opencode            # claude | opencode
  claude:
    model: opus
    effort: max
  opencode:
    # A valid opencode "provider/model" (see: opencode models)
    model: opencode/deepseek-v4-flash-free
    effort: max
```

- `backend` selects which CLI writes candidates. `--proposer {claude,opencode}`
  overrides it per run.
- For `opencode`, `model` **must** be a valid `provider/model` string; the run
  aborts if it is unset.
- On each proposer run, `opencode_wrapper.py` generates a temporary agent file at
  `.opencode/agent/<name>.md` (injecting the system prompt + tool allowlist) and
  removes it afterward.

## Layout Notes

- `agents/`: the kept baselines plus the write target for generated candidates.
- `.claude/skills/meta-harness/SKILL.md`: the proposer prior; it is shared by
  both backends (opencode receives its contents via the generated agent file).
- `.opencode/`: opencode workspace config (plugin dependency in
  `package.json`).

## Runtime And Cost

Two model roles are involved:

- **Solver model** — evaluates each memory system in the inner loop. Set under
  `models:` in `config.yaml` (default: `gemini/gemini-3.1-flash-lite`), or pass
  `--model`. Any LiteLLM-supported provider or OpenAI-compatible endpoint works;
  add `api_base` for a custom host.
- **Proposer model** — the agentic CLI that writes candidates, set under
  `proposer:` as described above.

The paper experiments used a local `vllm` deployment of `gpt-oss-120b`, MXFP4
quantized, with `max-model-len=32768`. API-backed runs may differ in quality.

## Release Notes

- `config.yaml` is the source of truth for datasets, solver models, active
  memory systems, and the proposer backend.
- The public release includes the MCE paper datasets under `data/`, so there is
  no runtime clone step.
- `inner_loop.py` uses package-mode imports, so the single-candidate command
  above keeps `PYTHONPATH=..` when run from this directory.
- `benchmark.py` is the sweep/orchestration layer used by `meta_harness.py`;
  `inner_loop.py` is the single memory-system evaluator that `benchmark.py`
  dispatches.
