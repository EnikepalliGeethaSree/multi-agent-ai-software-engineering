# Configuration comparison: detection

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.

## correct

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 40 | 15 | 12 | 0.7011 |
| static_only | static_llm | 40 | 13 | 15 | 0.8506 |
| static_only | static_llm_rag | 40 | 15 | 15 | 1.0000 |
| llm_only | static_llm | 40 | 1 | 6 | 0.1250 |
| llm_only | static_llm_rag | 40 | 6 | 9 | 0.6072 |
| static_llm | static_llm_rag | 40 | 7 | 5 | 0.7744 |

p-values are not corrected for the number of comparisons.
