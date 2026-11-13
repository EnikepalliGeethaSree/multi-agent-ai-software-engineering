# CodeReviewer msg (test, Python, n=40, seed=42, LLM Only)

n = 40 evaluated (0 failed: {}). Runtime 4992.3 s.

## All rules

Comment coverage (a comment was produced): 0.200

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.01 | 0.70 | 1.90 |
| title_fix | 0.77 | 2.64 | 3.56 |
| description | 0.77 | 2.51 | 3.68 |

- BLEU-4 (title_fix) 95% CI: 0.23-1.38

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.200

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.01 | 0.70 | 1.90 |
| title_fix | 0.77 | 2.64 | 3.56 |
| description | 0.77 | 2.51 | 3.68 |

- BLEU-4 (title_fix) 95% CI: 0.23-1.38
