# CodeReviewer msg (test, Python, n=40, seed=42, Static + LLM)

n = 40 evaluated (0 failed: {}). Runtime 6003.4 s.

## All rules

Comment coverage (a comment was produced): 0.600

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.73 | 2.27 | 6.35 |
| title_fix | 2.27 | 6.30 | 10.90 |
| description | 1.98 | 5.84 | 9.62 |

- BLEU-4 (title_fix) 95% CI: 1.43-3.16

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.400

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.42 | 1.02 | 3.72 |
| title_fix | 1.50 | 3.94 | 6.96 |
| description | 1.55 | 4.23 | 6.73 |

- BLEU-4 (title_fix) 95% CI: 0.77-2.37
