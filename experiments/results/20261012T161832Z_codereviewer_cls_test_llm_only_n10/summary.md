# CodeReviewer cls (test, Python, n=10, seed=42, LLM Only)

n = 10 evaluated (0 failed: {}), labels = {'positive': 5, 'negative': 5}. Findings per sample: 0.8; runtime 482.8 s.

## All rules

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.700 | 0.625 | 1.000 | 0.769 | 0.800 |
| low | 0.700 | 0.625 | 1.000 | 0.769 | 0.800 |
| medium | 0.700 | 0.667 | 0.800 | 0.727 | 0.600 |
| high | 0.600 | 0.600 | 0.600 | 0.600 | 0.500 |
| critical | 0.500 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.700 (95% CI 0.400-1.000), precision 0.625 (95% CI 0.250-1.000), F1 0.769 (95% CI 0.400-1.000)
- ROC-AUC of the finding score: 0.560
- Baselines: majority-class accuracy 0.500; always-positive F1 0.667

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Each sample is one hunk of a larger commit, so these rules fire on imports/names that
live in other hunks. Both analyses are reported; neither replaces the other.

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.700 | 0.625 | 1.000 | 0.769 | 0.800 |
| low | 0.700 | 0.625 | 1.000 | 0.769 | 0.800 |
| medium | 0.700 | 0.667 | 0.800 | 0.727 | 0.600 |
| high | 0.600 | 0.600 | 0.600 | 0.600 | 0.500 |
| critical | 0.500 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.700 (95% CI 0.400-1.000), precision 0.625 (95% CI 0.250-1.000), F1 0.769 (95% CI 0.400-1.000)
- ROC-AUC of the finding score: 0.560
- Baselines: majority-class accuracy 0.500; always-positive F1 0.667
