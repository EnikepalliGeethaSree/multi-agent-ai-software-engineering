# Change review: reviewing a pull request, not just a codebase

Real code review happens on a *change*: a pull request, a branch, or the work you are about to commit.
This feature turns the Code Review Agent into that kind of reviewer. It is based on the CodeReviewer
paper (Li et al., ESEC/FSE 2022) and the code-review-automation literature it builds on (decisions
D16-D20 in `decisions.md`).

## What you get

For a change, the agent reports:

1. **A change summary.** Files and lines changed, which functions were added, modified or removed,
   whose signature changed, and a short PR-style narrative (with an LLM). It also lists the **unchanged
   files that call the changed code**.
2. **Breaks outside the diff.** Code that the change did *not* touch but that no longer fits it.
   A diff-only reviewer cannot see these.
   - `IMPACT-REMOVED`: a removed function is still called.
   - `IMPACT-SIGNATURE`: a call no longer matches the new signature. This is checked the same way
     Python binds arguments: missing required, too many positional, unknown keyword. Calls with
     `*args`/`**kwargs` are not judged.
   - `IMPACT-BEHAVIOR` (LLM): the function now behaves differently in a way an untouched caller does
     not handle, for example it can now return `None`. The LLM sees the old version, the new version
     and the callers. Its findings go through the same evidence validation as every other LLM finding.
   - `TYPE-*` (mypy, when installed): type errors at call sites in impacted files.
3. **The normal review, scoped to the changed lines.** This covers static analysis, the LLM review,
   validation, dedup, the severity rubric and confidence.
4. **"Review these hunks first".** Every changed hunk is ranked by risk, with readable reasons and its
   diff.
5. **Suggested fixes** where possible (see below), never applied automatically.

Outputs: JSON, Markdown, PDF, **SARIF 2.1.0** (GitHub code scanning, IDEs), the dashboard, and an exit
code for CI and pre-commit gates.

## How to use it

```bash
# uncommitted work vs HEAD
python -m marl_agents.cli review-change path/to/repo
# what `git commit` would record now
python -m marl_agents.cli review-change . --staged
# a branch, like a pull request
python -m marl_agents.cli review-change . --base main --head feature/users
# two snapshots (no git needed)
python -m marl_agents.cli review-change --before v1.zip --after v2.zip

# common options
--mode static_only|full|llm_only    # static_only is free and takes seconds
--formats json,md,pdf,sarif
--fail-on high                      # exit 1 if a finding at/above this severity exists (CI gate)
```

- **Pre-commit hook:** run `python scripts/install_hooks.py path/to/repo`. The hook reviews staged
  Python changes and blocks the commit on `high` findings. Configure it with `MARL_REVIEW_MODE`,
  `MARL_FAIL_ON` and `MARL_PYTHON`. Skip it once with `git commit --no-verify`.
- **CI:** `examples/ci/github-code-review.yml` reviews each pull request, uploads SARIF (so findings
  appear as annotations on the PR) and fails the check on `high` findings.
- **Dashboard:** New review -> "Review a change". Choose a local git repository (working tree, staged,
  or two refs) or two ZIPs. A local repository can only be read when the dashboard runs on the same
  machine (D20).

Safety: git is read with `ls-tree` and `cat-file --batch` (raw blobs). There is no checkout, no hooks,
no filters and no `fsmonitor`. Refs are validated, so `--upload-pack=...` and the like are rejected.
The analysed code is never executed. mypy runs with our own empty config, so plugins from the
repository are never loaded.

## Hunk risk score (model v2)

The score is the **estimated chance (%) that a reviewer comments on the hunk**:
`100 * sigmoid(logit)`. Four weights were calibrated by logistic regression on the CodeReviewer `cls`
**validation** split (Python, n=4,219; run `20261005T111337Z_hunkrisk_cls_valid_n4220`, script
`scripts/calibrate_hunk_risk.py`). The test split was used once, for the reported number (D17).

| Signal | Weight (logit) | Source |
|---|---:|---|
| Intercept | -0.318 | calibrated |
| Touches security-sensitive APIs (eval/exec, pickle, subprocess, SQL execute, weak hashes, `verify=False`, secrets...) | +0.454 | calibrated |
| Changes error handling (`try`/`except`/`raise`/`finally`) | +0.648 | calibrated |
| Changes a function signature | +0.234 | calibrated |
| Size: per doubling of changed lines (`log2(1 + lines)`) | +0.055 | calibrated |
| Breaks call sites in other code (impact findings) | +1.0 each, max +2.0 | expert (never occurs in single-file samples) |
| Changed public function that no test references (when the repo has tests) | +0.3 | expert (no data) |

Levels: **high** at 59.7 or more and **medium** at 47.4 or more (the 90th and 65th percentiles on
the validation split), otherwise **low**.

**Guardrail:** a hunk with a critical finding is always high, and one with a high finding is at
least medium.

Some signals are listed as reasons but carry no weight. On the validation split their fitted
weight was zero or negative, and a signal must never *lower* risk:
- findings inside the hunk;
- removed functions;
- callers not updated in the same file.

The v1 model used hand-set additive points and ranked worse than chance (see `docs/results.md`).

## Suggested fixes

| Source | When it is shown | Label |
|---|---|---|
| Ruff autofix | Ruff offers a fix for the rule | **verified** if Ruff marks it *safe*; otherwise "review before applying" (Ruff's *unsafe* fixes can change behaviour) |
| LLM (medium+ findings, max 8 per review) | patch stays in the finding's region, parses, and re-analysis (Ruff + AST checks + secrets) finds **no new issue** | **verified** only if the tool-detected issue is gone; otherwise "suggested" |

Rejected LLM fixes are counted by reason (`outside_region`, `does_not_parse`, `introduces_issues`,
`issue_still_present`, ...) in `stats.fixes`. Security findings about secrets get no generated fix.

## Actionability filter

Industrial studies name vague recommendations and information overload as the main reasons
developers ignore review bots. LLM-only findings are checked for:
- vague wording without a concrete code reference;
- no concrete fix;
- a question instead of a stated problem;
- a missing explanation.

Two or more problems drop the finding. One problem downgrades it to `info`, with a note. The counts
are in `stats.vague_dropped` and `stats.vague_downgraded`.

## Evaluation

| Question | Command | Data |
|---|---|---|
| Does the risk ranking point at hunks humans commented on? | `eval hunkrisk` | CodeReviewer `cls`, all Python test samples |
| How useful are the comments? | `eval codereviewer --task msg --mode full`, then `eval usefulness --from-run <run> --judge-model <other model>` | CodeReviewer `msg` subset |
| Can the LLM judge be trusted? | rate `human_kit/rating_sheet.csv` (2 people), then `eval agreement --key key.csv --sheets a.csv,b.csv` | the same items |

The numbers are in `docs/results.md`. Every number comes from a saved run under `experiments/results/`.

## Limitations

- Python only. Calls through dynamic dispatch, `getattr` or `*args` forwarding are not resolved, so
  the impact analysis can miss callers. It never guesses: unresolvable calls are not reported.
- On CodeReviewer each sample is a single file, so cross-file signals rarely fire there. They are
  tested on multi-file git fixtures instead (`tests/unit/agents/test_change_review.py`).
- The LLM summary and behaviour checks depend on the model and cost tokens. `static_only` gives the
  deterministic parts for free.
