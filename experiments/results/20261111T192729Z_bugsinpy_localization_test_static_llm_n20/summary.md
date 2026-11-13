# Fault localization: static_llm

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.350 (0.150-0.600) | 0.550 | 0.0009 |
| Top-3 | 0.400 | 0.550 | 0.0028 |
| Top-5 | 0.400 (0.200-0.600) | 0.600 | 0.0047 |
| MRR | 0.374 (0.182-0.603) | 0.572 | |

- Gold function among the candidates: 0.750; shown to the LLM: 0.526
- Candidates per bug: 301.9; LLM calls: 19
- Wilson 95% interval, function Top-1: 0.350 (7/20; 95% CI 0.181-0.567)
- Wilson 95% interval, function Top-3: 0.400 (8/20; 95% CI 0.219-0.613)
- Wilson 95% interval, function Top-5: 0.400 (8/20; 95% CI 0.219-0.613)
