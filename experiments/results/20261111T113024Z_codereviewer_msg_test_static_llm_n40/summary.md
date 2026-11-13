# CodeReviewer msg (test, Python, n=40, seed=42, Static + LLM)

n = 40 evaluated (0 failed: {}). Runtime 231.2 s.

## All rules

Comment coverage (a comment was produced): 0.700

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.53 | 1.36 | 7.61 |
| title_fix | 1.89 | 5.97 | 13.28 |
| description | 2.29 | 6.15 | 13.08 |

- BLEU-4 (title_fix) 95% CI: 1.36-2.50

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.525

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.61 | 1.71 | 5.83 |
| title_fix | 1.23 | 4.08 | 9.42 |
| description | 1.90 | 4.40 | 9.71 |

- BLEU-4 (title_fix) 95% CI: 0.76-1.75
