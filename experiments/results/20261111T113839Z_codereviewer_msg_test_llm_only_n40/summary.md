# CodeReviewer msg (test, Python, n=40, seed=42, LLM Only)

n = 40 evaluated (0 failed: {}). Runtime 165.9 s.

## All rules

Comment coverage (a comment was produced): 0.650

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.81 | 1.59 | 7.62 |
| title_fix | 1.65 | 5.66 | 11.75 |
| description | 1.60 | 5.63 | 12.64 |

- BLEU-4 (title_fix) 95% CI: 1.13-2.21

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.650

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.81 | 1.59 | 7.62 |
| title_fix | 1.65 | 5.66 | 11.75 |
| description | 1.60 | 5.63 | 12.64 |

- BLEU-4 (title_fix) 95% CI: 1.13-2.21
