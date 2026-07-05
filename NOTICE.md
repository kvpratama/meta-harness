# Attribution

This project is derived from **Meta-Harness**, released under the MIT License.

- Upstream repository: https://github.com/stanford-iris-lab/meta-harness
- Paper: *Meta-Harness: End-to-End Optimization of Model Harnesses*
  (https://arxiv.org/abs/2603.28052)
- Original authors: Yoonho Lee, Roshen Nair, Qizheng Zhang, Kangwook Lee,
  Omar Khattab, Chelsea Finn (Stanford IRIS Lab)
- Original copyright: © 2026 Yoonho Lee (see [LICENSE](LICENSE))

## What this repository includes

A focused subset of the upstream project, plus an opencode proposer backend:

- [`tutorial/`](tutorial/) — the upstream conceptual walkthrough, unmodified.
- [`reference_examples/text_classification_opencode/`](reference_examples/text_classification_opencode/) —
  the text-classification experiment with an added **opencode** proposer backend
  (alongside the original Claude Code backend), for wider accessibility.

## What is original to this repository

The `text_classification_opencode` variant — the opencode proposer backend and
its supporting plumbing (`agent_runner.py`, `opencode_wrapper.py`, backend
selection in `config.yaml`, and the `.opencode/` workspace) — was contributed by
this repository's author. It builds directly on the upstream Meta-Harness
framework and the original `text_classification` example.

The upstream LICENSE and CITATION are preserved verbatim in this repository.
Please cite the original paper (see [CITATION.cff](CITATION.cff)) when using this
work.
