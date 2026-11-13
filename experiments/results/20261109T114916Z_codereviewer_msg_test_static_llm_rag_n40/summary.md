# CodeReviewer msg (test, Python, n=40, seed=42, Static + LLM + RAG)

n = 40 evaluated (0 failed: {}). Runtime 8536.7 s.

## All rules

Comment coverage (a comment was produced): 0.625

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.89 | 2.75 | 6.86 |
| title_fix | 2.59 | 6.53 | 10.98 |
| description | 1.90 | 5.87 | 10.13 |

- BLEU-4 (title_fix) 95% CI: 1.67-3.48

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Comment coverage (a comment was produced): 0.425

| Comment variant | BLEU-4 (smoothed) | ROUGE-L | chrF |
|---|---:|---:|---:|
| title | 0.58 | 1.57 | 4.13 |
| title_fix | 1.73 | 4.07 | 7.19 |
| description | 1.47 | 4.04 | 6.90 |

- BLEU-4 (title_fix) 95% CI: 0.97-2.57
