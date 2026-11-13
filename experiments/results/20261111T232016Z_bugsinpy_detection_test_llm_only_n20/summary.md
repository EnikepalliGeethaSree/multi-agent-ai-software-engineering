# Bug detection: llm_only

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 20 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.467 | 0.700 | 0.560 | 0.450 |
| Defect at the fixed lines | 0.360 | 0.450 | 0.400 | 0.325 |

- F1 95% CI: (0.364-0.714); AUC: 0.390
- Told apart from the fix: 0.050 (only buggy 1, both 13, neither 3, only fixed 3)
- LLM calls: 44; LLM findings rejected: 0
- Wilson 95% intervals (any defect in the function): precision 0.467 (14/30; 95% CI 0.302-0.639); recall 0.700 (14/20; 95% CI 0.481-0.855); told apart from the fix 0.050 (1/20; 95% CI 0.009-0.236)
