# Fault localization: llm_only

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.550 (0.350-0.750) | 0.650 | 0.0109 |
| Top-3 | 0.600 | 0.750 | 0.0318 |
| Top-5 | 0.600 (0.400-0.800) | 0.800 | 0.0515 |
| MRR | 0.581 (0.390-0.781) | 0.721 | |

- Gold function among the candidates: 0.850; shown to the LLM: 0.700
- Candidates per bug: 108.2; LLM calls: 20
- Wilson 95% interval, function Top-1: 0.550 (11/20; 95% CI 0.342-0.742)
- Wilson 95% interval, function Top-3: 0.600 (12/20; 95% CI 0.387-0.781)
- Wilson 95% interval, function Top-5: 0.600 (12/20; 95% CI 0.387-0.781)
