# CodeReviewer cls (test, Python, n=10, seed=42, Static + LLM)

n = 3 evaluated (7 failed: {'llm': 7}), labels = {'positive': 2, 'negative': 1}. Findings per sample: 1.0; runtime 239.2 s.

## All rules

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.667 | 0.667 | 1.000 | 0.800 | 1.000 |
| low | 0.667 | 0.667 | 1.000 | 0.800 | 1.000 |
| medium | 1.000 | 1.000 | 1.000 | 1.000 | 0.667 |
| high | 0.333 | 0.000 | 0.000 | 0.000 | 0.000 |
| critical | 0.333 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.667 (95% CI 0.000-1.000), precision 0.667 (95% CI 0.000-1.000), F1 0.800 (95% CI 0.000-1.000)
- ROC-AUC of the finding score: 1.000
- Baselines: majority-class accuracy 0.667; always-positive F1 0.800

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Each sample is one hunk of a larger commit, so these rules fire on imports/names that
live in other hunks. Both analyses are reported; neither replaces the other.

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 1.000 | 1.000 | 1.000 | 1.000 | 0.667 |
| low | 1.000 | 1.000 | 1.000 | 1.000 | 0.667 |
| medium | 1.000 | 1.000 | 1.000 | 1.000 | 0.667 |
| high | 0.333 | 0.000 | 0.000 | 0.000 | 0.000 |
| critical | 0.333 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 1.000 (95% CI 1.000-1.000), precision 1.000 (95% CI 0.000-1.000), F1 1.000 (95% CI 0.000-1.000)
- ROC-AUC of the finding score: 1.000
- Baselines: majority-class accuracy 0.667; always-positive F1 0.800
