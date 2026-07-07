# Terminal-Bench 2

Terminal-Bench 2 reference experiment for Meta-Harness. The default search config in this release uses Harbor on the full 89-task TB2 dataset, with 2 search trials per task on Opus 4.6.

## Quick Start

Install:

```bash
cd reference_examples/terminal_bench_2
uv sync
```

Read setup details first:

```bash
sed -n '1,200p' SETUP.md
```

Start with a cheap smoke check:

```bash
uv run bash scripts/run_eval.sh agents.baseline_kira:AgentHarness full 1 1 -i extract-elf
```

When trying a new idea, validate it on the cheaper 30-task `hard` subset before paying for a full default search:

```bash
uv run bash scripts/run_eval.sh agents.baseline_kira:AgentHarness hard 1 50
```

Run one evolve iteration with the default full-dataset search config:

```bash
uv run python meta_harness.py --iterations 1
```

Pass `--full-eval` if you also want the optional 5-trial winner pass on the full dataset.

## Proposer Backends

The proposer (the agentic CLI that writes candidate agents) supports two backends,
selectable at the command line. Backend-agnostic plumbing lives in
[`agent_runner.py`](agent_runner.py); the backends are
[`claude_wrapper.py`](claude_wrapper.py) and [`opencode_wrapper.py`](opencode_wrapper.py).

- **claude** (default): uses Claude Code (`claude -p`), model `opus`.
- **opencode**: uses `opencode run --format json`. Requires an explicit
  `provider/model` string (run `opencode models` to list valid identifiers).

```bash
# default (Claude Code)
uv run python meta_harness.py --iterations 1

# opencode backend
uv run python meta_harness.py --iterations 1 \
  --proposer opencode --proposer-model openrouter/openai/gpt-oss-120b
```

Relevant flags: `--proposer {claude,opencode}`, `--proposer-model MODEL`,
`--proposer-effort EFFORT` (default `max`). The shared skill prior
(`.claude/skills/meta-harness-terminal-bench-2/SKILL.md`) is used by both backends;
opencode receives it via a temporary agent file generated at
`.opencode/agent/<name>.md` (auto-removed after each run). Proposer sessions are
logged under `logs/<backend>_sessions/`.

## Repro And Troubleshooting

- The shipped `runloop` path requires both `ANTHROPIC_API_KEY` and `RUNLOOP_API_KEY`.
- The default paper-style config in this release is Opus 4.6, `full`, `89` tasks, `2` search trials, and concurrency `50`.
- Anthropic API tier matters for both speed and failure rate.
- Sharing the same Anthropic API key with other active projects can make runs substantially slower.
- Many failures at higher concurrency are timeout failures caused by insufficient API throughput, not necessarily reasoning failures.
- The recommended bring-up order is `extract-elf`, then `hard`, then the full default run.

## Key Files

- `.claude/skills/meta-harness-terminal-bench-2/SKILL.md`: proposer prior used by `meta_harness.py` (shared by both proposer backends).
- `agent_runner.py`: backend-agnostic proposer base (subprocess streaming, logging, skill loading).
- `claude_wrapper.py` / `opencode_wrapper.py`: proposer backends (Claude Code and opencode).
- `.opencode/`: opencode workspace config (plugin dependency); generated agent files land in `.opencode/agent/`.
- `agents/`: baseline agents and the write target for generated candidates.
- `prompt-templates/terminus-kira.txt`: prompt template used by `baseline_kira.py`.

## Runtime And Cost

With Opus 4.6 and a high-tier API key, the default 89x2 search run at concurrency `50` takes about 4-6 hours and costs roughly $500 _per iteration_. The recommended bring-up path is `extract-elf`, then `hard`, then the full default run.

This setup is sensitive to concurrency and Anthropic API throughput. API tier matters, and sharing the same API key with other active projects can make runs much slower. Many failures at higher concurrency are timeout failures caused by insufficient API throughput at the chosen setting.
