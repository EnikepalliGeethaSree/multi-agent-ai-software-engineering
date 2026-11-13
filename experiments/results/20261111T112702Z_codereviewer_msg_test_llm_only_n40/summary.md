# CodeReviewer msg (test, Python, n=40, seed=42, LLM Only)

n = 40 evaluated (0 failed: {}). Runtime 187.2 s.

## All rules

Comment coverage (a comment was produced): 0.625

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.69 | 1.64 | 7.07 |
| title_fix | 1.54 | 4.79 | 10.83 |
| description | 1.51 | 4.73 | 11.82 |

- BLEU-4 (title_fix) 95% CI: 1.02-2.04

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.625

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.69 | 1.64 | 7.07 |
| title_fix | 1.54 | 4.79 | 10.83 |
| description | 1.51 | 4.73 | 11.82 |

- BLEU-4 (title_fix) 95% CI: 1.02-2.04
