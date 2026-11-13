# Fault localization: static_only

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.150 (0.000-0.350) | 0.350 | 0.0009 |
| Top-3 | 0.250 | 0.500 | 0.0028 |
| Top-5 | 0.350 (0.150-0.550) | 0.500 | 0.0047 |
| MRR | 0.227 (0.079-0.393) | 0.442 | |

- Gold function among the candidates: 0.750
- Candidates per bug: 301.9; LLM calls: 0
- Wilson 95% interval, function Top-1: 0.150 (3/20; 95% CI 0.052-0.360)
- Wilson 95% interval, function Top-3: 0.250 (5/20; 95% CI 0.112-0.469)
- Wilson 95% interval, function Top-5: 0.350 (7/20; 95% CI 0.181-0.567)
