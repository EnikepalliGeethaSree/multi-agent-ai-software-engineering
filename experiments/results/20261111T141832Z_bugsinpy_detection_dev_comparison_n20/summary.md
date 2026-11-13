# Configuration comparison: detection

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.

## correct

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 40 | 13 | 11 | 0.8388 |
| static_only | static_llm | 40 | 11 | 14 | 0.6900 |
| static_only | static_llm_rag | 40 | 9 | 13 | 0.5235 |
| llm_only | static_llm | 40 | 3 | 8 | 0.2266 |
| llm_only | static_llm_rag | 40 | 2 | 8 | 0.1094 |
| static_llm | static_llm_rag | 40 | 4 | 5 | 1.0000 |

p-values are not corrected for the number of comparisons.
