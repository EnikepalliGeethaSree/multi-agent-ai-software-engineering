# CodeReviewer msg (test, Python, n=40, seed=42, Static + LLM + RAG)

n = 40 evaluated (0 failed: {}). Runtime 230.8 s.

## All rules

Comment coverage (a comment was produced): 0.750

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.59 | 1.32 | 8.23 |
| title_fix | 1.94 | 5.44 | 13.16 |
| description | 2.07 | 5.99 | 12.87 |

- BLEU-4 (title_fix) 95% CI: 1.42-2.45

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.600

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.68 | 1.67 | 7.54 |
| title_fix | 1.48 | 4.20 | 10.34 |
| description | 1.72 | 4.82 | 10.28 |

- BLEU-4 (title_fix) 95% CI: 0.98-2.00
