# Fault localization: static_only

- BugsInPy dev split, n=28 bugs (of 28 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- **Mock LLM:** this run tests the pipeline. Its numbers mean nothing.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.179 (0.036-0.321) | 0.607 | 0.0066 |
| Top-3 | 0.250 | 0.714 | 0.0199 |
| Top-5 | 0.250 (0.107-0.429) | 0.750 | 0.0331 |
| MRR | 0.229 (0.090-0.379) | 0.662 | |

- Gold function among the candidates: 0.357
- Candidates per bug: 9.4; LLM calls: 0
