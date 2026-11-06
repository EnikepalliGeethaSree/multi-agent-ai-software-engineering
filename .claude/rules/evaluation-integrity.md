---
paths:
  - "src/marl_agents/evaluation/**"
  - "experiments/**"
  - "capstone-datasets/**"
  - "docs/**"
---

# Evaluation integrity (this is a graded research project)

- **Never fabricate, estimate, or "fill in" results.** Every number in a table comes from a saved run under
  `experiments/results/<run_id>/` containing: config, git commit, model + provider, prompt versions,
  dataset + split + sample IDs, seed, raw predictions, and computed metrics.
- If a run was on a subset, say so everywhere the number appears (e.g. "n=200 random Python samples, seed 42").
- Compare A/B/C configurations on the **identical** sample set, model, temperature and prompts except for
  the variable under test.
- Don't tune prompts on the test split. Use train/valid (or a held-out dev slice) for prompt iteration;
  touch test only for final numbers.
- Never put benchmark ground truth (reference comments, fix patches, labels) into a RAG index or prompt
  used to answer that benchmark.
- Report failures honestly: parse failures, timeouts and rejected findings are counted, not silently dropped.
- Metric implementations must have unit tests with hand-computed expected values.
- `capstone-datasets/` is **read-only**. Never modify, move, or delete it; write derived/cached data to
  `data/cache/` instead. It is ~11 GB — never read whole files into context; sample with `head` or a script.

# Execution-based evaluation (HumanEval, BugsInPy, SWE-bench)

Running generated tests or patches is allowed **only** inside the evaluation harness, in an isolated
environment (Docker container or throwaway venv), with timeouts, and never on user-uploaded repos.
