# Configuration comparison: localization

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.

## top_1

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 20 | 1 | 5 | 0.2188 |
| static_only | static_llm | 20 | 1 | 5 | 0.2188 |
| static_only | static_llm_rag | 20 | 2 | 4 | 0.6875 |
| llm_only | static_llm | 20 | 1 | 1 | 1.0000 |
| llm_only | static_llm_rag | 20 | 3 | 1 | 0.6250 |
| static_llm | static_llm_rag | 20 | 2 | 0 | 0.5000 |

## top_5

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 20 | 0 | 3 | 0.2500 |
| static_only | static_llm | 20 | 0 | 1 | 1.0000 |
| static_only | static_llm_rag | 20 | 0 | 1 | 1.0000 |
| llm_only | static_llm | 20 | 2 | 0 | 0.5000 |
| llm_only | static_llm_rag | 20 | 2 | 0 | 0.5000 |
| static_llm | static_llm_rag | 20 | 0 | 0 | 1.0000 |

p-values are not corrected for the number of comparisons.
