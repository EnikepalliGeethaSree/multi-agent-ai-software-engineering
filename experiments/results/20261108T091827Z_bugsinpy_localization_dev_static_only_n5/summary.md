# Fault localization: static_only

- BugsInPy dev split, n=5 bugs (of 5 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.200 (0.000-0.600) | 0.600 | 0.0264 |
| Top-3 | 0.400 | 0.600 | 0.0758 |
| Top-5 | 0.400 (0.000-0.800) | 1.000 | 0.1204 |
| MRR | 0.332 (0.050-0.700) | 0.700 | |

- Gold function among the candidates: 1.000
- Candidates per bug: 84.6; LLM calls: 0
