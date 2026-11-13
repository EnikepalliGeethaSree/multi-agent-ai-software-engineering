# Configuration comparison: localization

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.

## top_1

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 20 | 0 | 7 | 0.0156 |
| static_only | static_llm | 20 | 0 | 5 | 0.0625 |
| static_only | static_llm_rag | 20 | 0 | 6 | 0.0312 |
| llm_only | static_llm | 20 | 2 | 0 | 0.5000 |
| llm_only | static_llm_rag | 20 | 2 | 1 | 1.0000 |
| static_llm | static_llm_rag | 20 | 1 | 2 | 1.0000 |

## top_5

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 20 | 0 | 6 | 0.0312 |
| static_only | static_llm | 20 | 0 | 4 | 0.1250 |
| static_only | static_llm_rag | 20 | 0 | 6 | 0.0312 |
| llm_only | static_llm | 20 | 2 | 0 | 0.5000 |
| llm_only | static_llm_rag | 20 | 1 | 1 | 1.0000 |
| static_llm | static_llm_rag | 20 | 0 | 2 | 0.5000 |

p-values are not corrected for the number of comparisons.
