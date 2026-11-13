# CodeReviewer msg (test, Python, n=40, seed=42, Static + LLM + RAG)

n = 40 evaluated (0 failed: {}). Runtime 274.5 s.

## All rules

Comment coverage (a comment was produced): 0.675

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.96 | 1.71 | 7.38 |
| title_fix | 1.55 | 4.89 | 12.27 |
| description | 2.08 | 6.42 | 11.62 |

- BLEU-4 (title_fix) 95% CI: 1.05-2.07

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.525

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 1.05 | 1.95 | 6.59 |
| title_fix | 1.23 | 3.68 | 9.77 |
| description | 1.83 | 5.33 | 9.63 |

- BLEU-4 (title_fix) 95% CI: 0.70-1.80
