# CodeReviewer msg (test, Python, n=40, seed=42, Static + LLM + RAG)

n = 40 evaluated (0 failed: {}). Runtime 221.9 s.

## All rules

Comment coverage (a comment was produced): 0.725

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 1.21 | 2.33 | 9.58 |
| title_fix | 2.25 | 5.92 | 14.04 |
| description | 2.24 | 6.54 | 13.76 |

- BLEU-4 (title_fix) 95% CI: 1.53-2.99

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.575

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 1.01 | 1.68 | 7.61 |
| title_fix | 1.62 | 4.19 | 10.50 |
| description | 1.71 | 5.08 | 10.50 |

- BLEU-4 (title_fix) 95% CI: 1.01-2.38
