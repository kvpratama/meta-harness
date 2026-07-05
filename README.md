# Meta-Harness (opencode edition)

A focused, accessible slice of [Meta-Harness](https://github.com/stanford-iris-lab/meta-harness)
that adds **[opencode](https://opencode.ai)** as a proposer backend so you can run
harness search without depending solely on Claude Code.

Meta-Harness is a framework for automated search over task-specific model
harnesses: the code around a fixed base model that decides what to store,
retrieve, and show while the model works. See the paper,
[Meta-Harness: End-to-End Optimization of Model Harnesses](https://arxiv.org/abs/2603.28052).

> **Credit:** This repository is derived from the original Meta-Harness by
> Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee, Omar Khattab, and
> Chelsea Finn (Stanford IRIS Lab), MIT-licensed. The opencode proposer backend
> is the contribution of this repository. See [NOTICE.md](NOTICE.md) for full
> attribution and [LICENSE](LICENSE) for the original license.

## Contents

- [`tutorial/`](tutorial/) — a 7-part conceptual walkthrough of the Meta-Harness
  idea, from the outer loop down to generalizing to a new domain.
- [`reference_examples/text_classification/`](reference_examples/text_classification/README.md) —
  the text-classification experiment with a selectable proposer backend
  (opencode by default, Claude Code as an alternate).

## Quick Start

```bash
cd reference_examples/text_classification
uv sync
uv run python meta_harness.py --iterations 1
```

Install and authenticate the proposer CLI (needed for `--iterations >= 1`):

- **opencode** (default): install per the [opencode docs](https://opencode.ai),
  then `opencode auth login`; list `provider/model` ids with `opencode models`.
- **claude** (alternate): install Claude Code and sign in.

See the [example README](reference_examples/text_classification/README.md)
for full setup, configuration, runtime, and cost details.

## Citation

If you use this work, please cite the original paper (details in
[CITATION.cff](CITATION.cff)):

```bibtex
@article{lee2026metaharness,
  title   = {Meta-Harness: End-to-End Optimization of Model Harnesses},
  author  = {Lee, Yoonho and Nair, Roshen and Zhang, Qizheng and
             Lee, Kangwook and Khattab, Omar and Finn, Chelsea},
  year    = {2026},
  journal = {arXiv preprint arXiv:2603.28052},
  url     = {https://arxiv.org/abs/2603.28052}
}
```

## License

MIT — see [LICENSE](LICENSE). Copyright © 2026 Yoonho Lee.
