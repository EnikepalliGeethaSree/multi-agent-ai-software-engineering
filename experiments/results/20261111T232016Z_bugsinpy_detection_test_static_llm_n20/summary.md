# Bug detection: static_llm

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 20 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.552 | 0.800 | 0.653 | 0.575 |
| Defect at the fixed lines | 0.458 | 0.550 | 0.500 | 0.450 |

- F1 95% CI: (0.462-0.793); AUC: 0.589
- Told apart from the fix: 0.200 (only buggy 4, both 12, neither 3, only fixed 1)
- LLM calls: 44; LLM findings rejected: 0
- Wilson 95% intervals (any defect in the function): precision 0.552 (16/29; 95% CI 0.375-0.716); recall 0.800 (16/20; 95% CI 0.584-0.919); told apart from the fix 0.200 (4/20; 95% CI 0.081-0.416)
