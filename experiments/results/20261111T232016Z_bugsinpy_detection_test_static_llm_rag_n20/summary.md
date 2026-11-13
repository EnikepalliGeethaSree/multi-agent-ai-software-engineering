# Bug detection: static_llm_rag

- BugsInPy test split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 20 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.516 | 0.800 | 0.627 | 0.525 |
| Defect at the fixed lines | 0.444 | 0.600 | 0.511 | 0.425 |

- F1 95% CI: (0.455-0.772); AUC: 0.552
- Told apart from the fix: 0.150 (only buggy 3, both 13, neither 2, only fixed 2)
- LLM calls: 44; LLM findings rejected: 0
- Wilson 95% intervals (any defect in the function): precision 0.516 (16/31; 95% CI 0.348-0.680); recall 0.800 (16/20; 95% CI 0.584-0.919); told apart from the fix 0.150 (3/20; 95% CI 0.052-0.360)
