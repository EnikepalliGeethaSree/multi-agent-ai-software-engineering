# CodeReviewer msg (test, Python, n=40, seed=42, LLM Only)

n = 40 evaluated (0 failed: {}). Runtime 161.8 s.

## All rules

Comment coverage (a comment was produced): 0.650

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.92 | 1.62 | 7.82 |
| title_fix | 1.47 | 5.20 | 10.69 |
| description | 1.60 | 5.12 | 11.90 |

- BLEU-4 (title_fix) 95% CI: 0.93-2.11

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.650

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.92 | 1.62 | 7.82 |
| title_fix | 1.47 | 5.20 | 10.69 |
| description | 1.60 | 5.12 | 11.90 |

- BLEU-4 (title_fix) 95% CI: 0.93-2.11
