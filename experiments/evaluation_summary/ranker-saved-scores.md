# Classifier as a hunk-risk ranker (saved-score secondary analysis)

**saved-score secondary analysis (test changes already used to evaluate the classifier; nothing re-scored; not used to choose a default).**

- Sources: hunk-risk run `20261012T085812Z_hunkrisk_cls_test_n4196` (risk v2, change size) and classifier test run `20261106T144800Z_classifier_cls_test_n1771` (saved scores).
- Repository-disjoint classifier test changes: 1771; scored by both runs: 1771; label mismatches excluded: 0; compared: n = 1771 (979 commented, base rate 0.553).
- Default ranker: risk_v2 (unchanged). This comparison does not change it.

| Ranker | ROC-AUC (95% CI) | Precision top 5% | top 10% | top 25% |
|---|---:|---:|---:|---:|
| Risk v2 (shipped) | 0.635 (0.609-0.662) | 0.807 | 0.819 | 0.731 |
| Change size | 0.634 (0.606-0.659) | 0.830 | 0.814 | 0.731 |
| Fine-tuned classifier (saved scores) | 0.723 (0.700-0.746) | 1.000 | 0.938 | 0.817 |

Random ranking: AUC 0.500, precision at any cut = base rate 0.553. AUC intervals: percentile bootstrap, 300 resamples, seed 42.
