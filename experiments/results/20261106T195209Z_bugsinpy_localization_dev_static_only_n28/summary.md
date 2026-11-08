# Fault localization: static_only

- BugsInPy dev split, n=28 bugs (of 28 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.179 (0.036-0.321) | 0.643 | 0.0085 |
| Top-3 | 0.250 | 0.821 | 0.0249 |
| Top-5 | 0.286 (0.107-0.464) | 0.893 | 0.0405 |
| MRR | 0.240 (0.113-0.390) | 0.744 | |

- Gold function among the candidates: 0.893
- Candidates per bug: 134.9; LLM calls: 0
