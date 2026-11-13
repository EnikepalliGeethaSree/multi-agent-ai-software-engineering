# Fault localization: static_llm_rag

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 0

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.500 (0.300-0.700) | 0.700 | 0.0109 |
| Top-3 | 0.600 | 0.800 | 0.0318 |
| Top-5 | 0.600 (0.400-0.800) | 0.900 | 0.0515 |
| MRR | 0.556 (0.360-0.751) | 0.775 | |

- Gold function among the candidates: 0.850; shown to the LLM: 0.700
- Candidates per bug: 111.5; LLM calls: 20
- Wilson 95% interval, function Top-1: 0.500 (10/20; 95% CI 0.299-0.701)
- Wilson 95% interval, function Top-3: 0.600 (12/20; 95% CI 0.387-0.781)
- Wilson 95% interval, function Top-5: 0.600 (12/20; 95% CI 0.387-0.781)
