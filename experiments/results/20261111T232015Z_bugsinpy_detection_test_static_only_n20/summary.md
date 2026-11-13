# Bug detection: static_only

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 20 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.667 | 0.100 | 0.174 | 0.525 |
| Defect at the fixed lines | 0.000 | 0.000 | 0.000 | 0.475 |

- F1 95% CI: (0.000-0.381); AUC: 0.525
- Told apart from the fix: 0.050 (only buggy 1, both 1, neither 18, only fixed 0)
- LLM calls: 0; LLM findings rejected: 0
- Wilson 95% intervals (any defect in the function): precision 0.667 (2/3; 95% CI 0.208-0.939); recall 0.100 (2/20; 95% CI 0.028-0.301); told apart from the fix 0.050 (1/20; 95% CI 0.009-0.236)
