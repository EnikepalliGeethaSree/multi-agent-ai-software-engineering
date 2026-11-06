# Comment usefulness (LLM judge) for 20261005T120433Z_codereviewer_msg_test_full_n40

Judge model: `openai/gpt-oss-20b` (reviewer: `qwen/qwen3.8-27b`). Prompt `usefulness` v1.0. Blind, reference-free, 1-5 scale.
Items judged: 64 of 64 (failures: none); samples where the agent produced no comment: 8.

| Comment author | n | Relevance (95% CI) | Informativeness (95% CI) | Rel >= 4 | Inf >= 4 |
|---|---:|---:|---:|---:|---:|
| Agent | 28 | 4.71 (4.29-5.00) | 4.64 (4.21-4.96) | 0.929 | 0.929 |
| Human reviewer (dataset) | 36 | 3.67 (3.22-4.08) | 3.00 (2.61-3.42) | 0.667 | 0.389 |

Paired comparison on 28 diffs with both comments (agent - human):

- relevance: +0.96 (95% CI +0.25 to +1.61); agent better 16, tie 10, human better 2
- informativeness: +1.57 (95% CI +0.89 to +2.18); agent better 22, tie 2, human better 4

An LLM judge is a proxy, not ground truth: check it against human ratings (`eval agreement`) before citing these numbers.
