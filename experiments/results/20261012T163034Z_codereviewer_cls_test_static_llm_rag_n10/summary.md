# CodeReviewer cls (test, Python, n=10, seed=42, Static + LLM + RAG)

n = 0 evaluated (10 failed: {'llm': 10}), labels = {'positive': 0, 'negative': 0}. Findings per sample: 0.0; runtime 3.3 s.

## All rules

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| low | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| medium | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| high | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| critical | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.000 (95% CI nan-nan), precision 0.000 (95% CI nan-nan), F1 0.000 (95% CI nan-nan)
- ROC-AUC: n/a
- Baselines: majority-class accuracy 0.000; always-positive F1 0.000

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Each sample is one hunk of a larger commit, so these rules fire on imports/names that
live in other hunks. Both analyses are reported; neither replaces the other.

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| low | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| medium | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| high | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |
| critical | 0.000 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.000 (95% CI nan-nan), precision 0.000 (95% CI nan-nan), F1 0.000 (95% CI nan-nan)
- ROC-AUC: n/a
- Baselines: majority-class accuracy 0.000; always-positive F1 0.000
