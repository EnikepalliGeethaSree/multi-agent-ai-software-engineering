# Fault localization: static_llm_rag

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- Failed samples, counted as misses: 1

| Metric | Function | File | Random function |
|---|---:|---:|---:|
| Top-1 | 0.250 (0.100-0.450) | 0.500 | 0.0009 |
| Top-3 | 0.400 | 0.550 | 0.0028 |
| Top-5 | 0.400 (0.200-0.600) | 0.550 | 0.0047 |
| MRR | 0.316 (0.153-0.510) | 0.543 | |

- Gold function among the candidates: 0.750; shown to the LLM: 0.550
- Candidates per bug: 321.2; LLM calls: 20
- Wilson 95% interval, function Top-1: 0.250 (5/20; 95% CI 0.112-0.469)
- Wilson 95% interval, function Top-3: 0.400 (8/20; 95% CI 0.219-0.613)
- Wilson 95% interval, function Top-5: 0.400 (8/20; 95% CI 0.219-0.613)
