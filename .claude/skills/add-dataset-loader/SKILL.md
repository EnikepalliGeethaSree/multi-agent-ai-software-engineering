---
name: add-dataset-loader
description: Add or update a loader for one of the benchmark datasets in capstone-datasets/ (CodeReviewer, BugsInPy, Devign, HumanEval, CodeSearchNet, SWE-bench Lite) that yields typed evaluation samples. Use when wiring a benchmark into evaluation.
---

# Add a benchmark dataset loader

`capstone-datasets/` is ~11 GB and **read-only**. Never load whole files into context — inspect with
`head -c`, `python -c` over the first few records, or `zipfile`/`gzip` listing.

## Known locations and formats

| Dataset | Path (under `capstone-datasets/`) | Format | Key fields |
|---|---|---|---|
| CodeReviewer – comment gen | `codereview/CodeBERT/CodeReviewer/dataset/Comment_Generation/msg-{train,valid,test}.jsonl` | JSONL | `patch`, `msg` (reference comment), `oldf`, `y`, `lang`? — verify |
| CodeReviewer – quality est. | `codereview/CodeBERT/CodeReviewer/dataset/Diff_Quality_Estimation.zip` | zip (not extracted) | extract to `data/cache/`, not in place |
| BugsInPy | `bugsinpy/projects/<project>/bugs/<id>/` | `bug.info`, `bug_patch.txt`, `run_test.sh`, `requirements.txt` | buggy/fixed commit, `test_file`; source requires git checkout |
| Devign | `devign/devign/data/raw/dataset.json` | JSON list (27,318) | `project`, `commit_id`, `target` (0/1), `func` — **C code** |
| HumanEval | `humaneval/human-eval/data/HumanEval.jsonl.gz` | gzipped JSONL (164) | `task_id`, `prompt`, `canonical_solution`, `test`, `entry_point` |
| CodeSearchNet (Python) | `codesearchnet/python/python/final/jsonl/{train,valid,test}/*.jsonl.gz` | gzipped JSONL | `code`, `docstring`, `func_name`, `path`, `repo` |
| SWE-bench Lite | `swebench/SWE-bench_Lite/{dev,test}/` | HF `datasets` arrow (23 dev / 300 test) | `instance_id`, `repo`, `base_commit`, `problem_statement`, `patch`, `test_patch`, `FAIL_TO_PASS`, `PASS_TO_PASS` |

Always verify field names against the actual first record before coding — the table is a guide.

## Steps

1. Inspect 1–3 records of the target file and confirm the schema.
2. Create `src/marl_agents/evaluation/datasets/<name>.py` with:
   - a Pydantic `<Name>Sample` model (only the fields the experiment needs + a stable `sample_id`);
   - `load_<name>(split: str, limit: int | None = None, seed: int = 42, languages: set[str] | None = None) -> Iterator[<Name>Sample]`
     that **streams** (no full-file materialisation for multi-GB files);
   - dataset root resolved from config `datasets.root` (default `capstone-datasets`).
3. Deterministic sampling: when `limit` is set, sample with the given seed and make the chosen
   `sample_id`s saveable so A/B/C runs use identical samples.
4. Add a tiny fixture (3–5 synthetic records in the same format) under `tests/fixtures/datasets/<name>/` and a
   unit test against it. Mark any test touching the real folder `@pytest.mark.dataset`.
5. Document the loader, split sizes and any filtering (e.g. Python-only) in `docs/datasets.md`.
