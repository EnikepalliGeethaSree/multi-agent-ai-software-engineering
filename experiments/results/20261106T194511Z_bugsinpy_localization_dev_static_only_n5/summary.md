# Fault localization: static_only

- BugsInPy dev split, n=5 bugs (of 5 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- **Incomplete:** 4 sample(s) not run yet. Run the same command again to continue; these numbers cover finished samples only.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.000 (0.000-0.000) | 1.000 | 0.0526 |
| Top-3 | 1.000 | 1.000 | 0.1579 |
| Top-5 | 1.000 (1.000-1.000) | 1.000 | 0.2632 |
| MRR | 0.333 (0.333-0.333) | 1.000 | |

- Gold function among the candidates: 1.000
- Candidates per bug: 4.0; LLM calls: 0
