# Bug detection: static_only

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 20 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.571 | 0.200 | 0.296 | 0.525 |
| Defect at the fixed lines | 0.400 | 0.100 | 0.160 | 0.475 |

- F1 95% CI: (0.080-0.516); AUC: 0.529
- Told apart from the fix: 0.050 (only buggy 1, both 3, neither 16, only fixed 0)
- LLM calls: 0; LLM findings rejected: 0
- Wilson 95% intervals (any defect in the function): precision 0.571 (4/7; 95% CI 0.250-0.842); recall 0.200 (4/20; 95% CI 0.081-0.416); told apart from the fix 0.050 (1/20; 95% CI 0.009-0.236)
