# Bug detection: static_llm_rag

- BugsInPy dev split, n=20 bugs (of 20 requested), seed 42. Pool: one source file, at most 10 changed lines, change inside a function.
- 20 bugs, each shown as its buggy and fixed function in separate requests.
- Failed requests, scored as wrong answers: 0
- A fixed function may still hold another bug, so false positives are an upper bound.

| Scoring | Precision | Recall | F1 | Accuracy |
|---|---:|---:|---:|---:|
| Any defect in the function | 0.593 | 0.800 | 0.681 | 0.625 |
| Defect at the fixed lines | 0.522 | 0.600 | 0.558 | 0.525 |

- F1 95% CI: (0.500-0.815); AUC: 0.636
- Told apart from the fix: 0.300 (only buggy 6, both 10, neither 3, only fixed 1)
- LLM calls: 40; LLM findings rejected: 1
- Wilson 95% intervals (any defect in the function): precision 0.593 (16/27; 95% CI 0.407-0.755); recall 0.800 (16/20; 95% CI 0.584-0.919); told apart from the fix 0.300 (6/20; 95% CI 0.145-0.519)
