# Datasets

Benchmarks are used for **evaluation**, not training. Stored in `capstone-datasets/` (~11 GB, read-only,
gitignored). Loaders go in `src/marl_agents/evaluation/datasets/` (see `/add-dataset-loader`).

| Dataset | Agent | Local path | Size on disk | Notes |
|---|---|---|---|---|
| CodeReviewer | Code Review | `codereview/CodeBERT/CodeReviewer/dataset/` | 6.7 GB (whole CodeBERT repo) | **Comment generation** `Comment_Generation/msg-*.jsonl`: train 117,739 (no `lang` field), valid 10,319, test 10,169; fields `patch, oldf, msg, y, id` (+ `idx, proj, lang` in valid/test). 9 languages; **Python: 1,420 valid / 1,403 test**. `y` is always 1 here (every diff has a comment). **Quality estimation** `Diff_Quality_Estimation.zip`: `cls-{train-chunk-0..3,valid,test}.jsonl`, ~15 GB uncompressed, not extracted — stream from the zip or extract to `data/cache/`. |
| BugsInPy | Bug Detection | `bugsinpy/projects/<project>/bugs/<id>/` | 9 MB | 17 projects, **502 bugs**. Per bug: `bug.info` (python version, buggy/fixed commit, test file), `bug_patch.txt` (gold fix diff), `run_test.sh`. Metadata only — source must be cloned at the buggy commit. |
| Devign | Security | `devign/devign/data/raw/dataset.json` | 264 MB | 27,318 functions (QEMU 17,549, FFmpeg 9,769); `target` 1 = vulnerable (12,460) / 0 (14,858). Fields `project, commit_id, target, func`. **C code.** |
| HumanEval | Test Generation | `humaneval/human-eval/data/HumanEval.jsonl.gz` | <1 MB | 164 Python problems: `task_id, prompt, canonical_solution, test` (`check(candidate)` asserts), `entry_point`. |
| CodeSearchNet (Python) | Documentation | `codesearchnet/python/python/final/jsonl/{train,valid,test}/` | 4.0 GB | gzipped JSONL: train 412,178, valid 23,107, test 22,176. Fields `repo, path, func_name, code, docstring, code_tokens, docstring_tokens, url, ...`. `code` still contains the docstring — strip it before generation. |
| SWE-bench Lite | System-level | `swebench/SWE-bench_Lite/{dev,test}/` | 4 MB | HF arrow (read with `pyarrow.ipc.open_stream`; the installed `datasets` is broken with current pyarrow). 23 dev + 300 test, 12 repos (django 114, sympy 77, ...). Fields `repo, instance_id, base_commit, problem_statement, patch, test_patch, FAIL_TO_PASS, PASS_TO_PASS, ...`. |

## Methodological caveats

- **CodeReviewer `cls` train labels leak through metadata.** All positives lack `lang` and `proj`, so
  `lang == "py"` selects negatives only. `valid` and `test` share 28 projects. Use `training/data.py`;
  see [fine-tuning.md](fine-tuning.md).

- **Devign vs. Python focus.** The product targets Python repos, but Devign is C. Options: evaluate the
  Security Agent's LLM reasoning language-agnostically on Devign (state this clearly), and/or add a Python
  security set later (e.g. Bandit test cases / CWE-labelled Python samples). Decision pending — see
  `decisions.md`.
- **CodeReviewer tasks.** Comment generation (BLEU vs. reference `msg`) and diff quality estimation
  (binary label `y`, F1/accuracy). Our agent emits structured findings, so comment-generation evaluation
  needs a mapping from findings to a review comment — document it when implemented.
- **Execution-based benchmarks** (HumanEval, BugsInPy, SWE-bench) run code only in an isolated harness.
