# Fault localization: static_llm

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.450 (0.250-0.650) | 0.600 | 0.0109 |
| Top-3 | 0.450 | 0.750 | 0.0318 |
| Top-5 | 0.500 (0.300-0.700) | 0.850 | 0.0515 |
| MRR | 0.476 (0.282-0.676) | 0.698 | |

- Gold function among the candidates: 0.850; shown to the LLM: 0.700
- Candidates per bug: 108.2; LLM calls: 20
- Wilson 95% interval, function Top-1: 0.450 (9/20; 95% CI 0.258-0.658)
- Wilson 95% interval, function Top-3: 0.450 (9/20; 95% CI 0.258-0.658)
- Wilson 95% interval, function Top-5: 0.500 (10/20; 95% CI 0.299-0.701)
