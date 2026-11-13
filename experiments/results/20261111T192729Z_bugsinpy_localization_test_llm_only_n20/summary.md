# Fault localization: llm_only

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 1

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.350 (0.150-0.550) | 0.550 | 0.0009 |
| Top-3 | 0.500 | 0.600 | 0.0028 |
| Top-5 | 0.500 (0.300-0.700) | 0.600 | 0.0047 |
| MRR | 0.425 (0.221-0.634) | 0.583 | |

- Gold function among the candidates: 0.700; shown to the LLM: 0.579
- Candidates per bug: 282.8; LLM calls: 19
- Wilson 95% interval, function Top-1: 0.350 (7/20; 95% CI 0.181-0.567)
- Wilson 95% interval, function Top-3: 0.500 (10/20; 95% CI 0.299-0.701)
- Wilson 95% interval, function Top-5: 0.500 (10/20; 95% CI 0.299-0.701)
