# Fault localization: static_only

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.200 (0.050-0.400) | 0.550 | 0.0109 |
| Top-3 | 0.250 | 0.750 | 0.0318 |
| Top-5 | 0.300 (0.100-0.500) | 0.850 | 0.0515 |
| MRR | 0.258 (0.105-0.441) | 0.667 | |

- Gold function among the candidates: 0.850
- Candidates per bug: 108.2; LLM calls: 0
- Wilson 95% interval, function Top-1: 0.200 (4/20; 95% CI 0.081-0.416)
- Wilson 95% interval, function Top-3: 0.250 (5/20; 95% CI 0.112-0.469)
- Wilson 95% interval, function Top-5: 0.300 (6/20; 95% CI 0.145-0.519)
