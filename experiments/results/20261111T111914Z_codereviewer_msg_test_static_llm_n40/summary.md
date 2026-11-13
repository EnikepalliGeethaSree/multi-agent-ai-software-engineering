# CodeReviewer msg (test, Python, n=40, seed=42, Static + LLM)

n = 40 evaluated (0 failed: {}). Runtime 200.1 s.

## All rules

Comment coverage (a comment was produced): 0.625

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.65 | 1.79 | 6.30 |
| title_fix | 1.75 | 4.81 | 11.18 |
| description | 1.29 | 3.90 | 9.75 |

- BLEU-4 (title_fix) 95% CI: 1.21-2.34

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.450

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.69 | 1.32 | 5.13 |
| title_fix | 1.18 | 3.04 | 7.96 |
| description | 1.08 | 2.74 | 7.04 |

- BLEU-4 (title_fix) 95% CI: 0.73-1.75
