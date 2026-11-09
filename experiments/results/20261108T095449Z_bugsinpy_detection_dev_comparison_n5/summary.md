# Configuration comparison: detection

- BugsInPy dev split, n=5 bugs (of 5 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.

## correct

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 10 | 1 | 0 | 1.0000 |
| static_only | static_llm | 10 | 0 | 0 | 1.0000 |
| static_only | static_llm_rag | 10 | 0 | 0 | 1.0000 |
| llm_only | static_llm | 10 | 0 | 1 | 1.0000 |
| llm_only | static_llm_rag | 10 | 0 | 1 | 1.0000 |
| static_llm | static_llm_rag | 10 | 0 | 0 | 1.0000 |

p-values are not corrected for the number of comparisons.
