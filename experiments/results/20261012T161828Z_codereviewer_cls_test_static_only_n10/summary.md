# CodeReviewer cls (test, Python, n=10, seed=42, Static Only)

n = 10 evaluated (0 failed: {}), labels = {'positive': 5, 'negative': 5}. Findings per sample: 1.0; runtime 2.8 s.

## All rules

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.300 | 0.250 | 0.200 | 0.222 | 0.400 |
| low | 0.300 | 0.250 | 0.200 | 0.222 | 0.400 |
| medium | 0.400 | 0.333 | 0.200 | 0.250 | 0.300 |
| high | 0.300 | 0.000 | 0.000 | 0.000 | 0.200 |
| critical | 0.500 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.300 (95% CI 0.000-0.600), precision 0.250 (95% CI 0.000-0.800), F1 0.222 (95% CI 0.000-0.571)
- ROC-AUC of the finding score: 0.280
- Baselines: majority-class accuracy 0.500; always-positive F1 0.667

## Sensitivity: without cross-hunk rules F401, F403, F405, F811, F821

Each sample is one hunk of a larger commit, so these rules fire on imports/names that
live in other hunks. Both analyses are reported; neither replaces the other.

| Threshold (min severity) | Accuracy | Precision | Recall | F1 | Positive rate |
|---|---:|---:|---:|---:|---:|
| info | 0.500 | 0.500 | 0.200 | 0.286 | 0.200 |
| low | 0.500 | 0.500 | 0.200 | 0.286 | 0.200 |
| medium | 0.600 | 1.000 | 0.200 | 0.333 | 0.100 |
| high | 0.500 | 0.000 | 0.000 | 0.000 | 0.000 |
| critical | 0.500 | 0.000 | 0.000 | 0.000 | 0.000 |

- Threshold `low`: accuracy 0.500 (95% CI 0.200-0.800), precision 0.500 (95% CI 0.000-1.000), F1 0.286 (95% CI 0.000-0.667)
- ROC-AUC of the finding score: 0.520
- Baselines: majority-class accuracy 0.500; always-positive F1 0.667
