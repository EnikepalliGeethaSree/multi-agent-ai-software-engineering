# Configuration comparison: localization

- BugsInPy dev split, n=5 bugs (of 5 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- **Incomplete:** 8 sample(s) not run yet. Run the same command again to continue; these numbers cover finished samples only.

## top_1

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 1 | 0 | 0 | 1.0000 |

## top_5

| A | B | n | Only A right | Only B right | McNemar p |
|---|---|---:|---:|---:|---:|
| static_only | llm_only | 1 | 0 | 0 | 1.0000 |

p-values are not corrected for the number of comparisons.
