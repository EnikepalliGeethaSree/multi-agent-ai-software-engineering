# CodeReviewer msg (test, Python, n=40, seed=42, LLM Only)

n = 20 evaluated (20 failed: {'llm': 20}). Runtime 303.8 s.

## All rules

Comment coverage (a comment was produced): 0.550

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 1.25 | 2.50 | 8.56 |
| title_fix | 1.48 | 3.87 | 9.61 |
| description | 1.59 | 4.10 | 9.82 |

- BLEU-4 (title_fix) 95% CI: 0.61-2.68

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.550

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 1.25 | 2.50 | 8.56 |
| title_fix | 1.48 | 3.87 | 9.61 |
| description | 1.59 | 4.10 | 9.82 |

- BLEU-4 (title_fix) 95% CI: 0.61-2.68
