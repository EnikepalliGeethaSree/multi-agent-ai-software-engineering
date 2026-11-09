# Bug Detection Agent

Finds defects in Python code and says what makes them fail. Given a failing test, it ranks where the
failure comes from. It reads code only: it never runs, imports or installs what it analyzes.

Approved design: deck Fig. 3. Results: [results.md](results.md), section 12. Decision: D31.

## Use it

```bash
# Scan a directory, ZIP or file (at most bugs.max_units LLM requests, riskiest code first)
python -m marl_agents.cli bugs path/to/repo --config configs/gemini.yaml

# A known failure: rank suspects, then read them for the bug
python -m marl_agents.cli bugs path/to/repo --failing-test tests/test_x.py::test_y
python -m marl_agents.cli bugs path/to/repo --failing-test tests/test_x.py::test_y --traceback out.txt

# A code change (git refs, working tree, staged, two ZIPs)
python -m marl_agents.cli review-change repo --base main --head feature --agent bug_detection

# No LLM: static checks only
python -m marl_agents.cli bugs path/to/repo --mode static_only
```

In the dashboard, choose **Bug detection** under Agent on the New review page.

From code:

```python
agent = BugDetectionAgent(llm, settings=settings)
result = agent.run(AgentRequest(repo_path="repo"))
result = agent.run(AgentRequest(repo_path="repo", options={"failing_test": "tests/t.py::test_x"}))
result.artifacts["localization"]  # a LocalizationResult, as a dict
```

## How it works

It is a specialized Code Review Agent. Ingestion, quota handling, resume, validation, deduplication,
the severity rubric, reports and suggested fixes are shared. These parts are its own:

| Fig. 3 stage | Implementation |
|---|---|
| 1. Input | Repository, ZIP, file, snippet, or a change; optionally a failing test and its traceback |
| 2. Code processing | AST and call graph (`parsing`), **control-flow graph** (`parsing/cfg.py`), review units |
| 3. Context retrieval | Call-graph neighbours, retrieved similar code, guidelines (`ContextBuilder`) |
| 4. LLM analysis | `agents/bug_detection/prompts/`: follow the paths, try inputs that break code |
| 5. Bug identification | `BugType`: logic, null/exception, boundary, resource leak, concurrency, security, other |
| 6. Bug report | `Finding` plus `BugDetail` (trigger, expected, actual, root cause, repro steps), severity, confidence, suggested fix |

### Control-flow checks

`static_analysis/flow_checks.py` works on one function's CFG. Its rules live in `FLOW_RULES`, so the
severity table decides severity, as for every tool.

| Rule | Finds |
|---|---|
| `BUG-NONE-DEREF` | A value that may be None is used without a check on some path |
| `BUG-NONE-DEFAULT` | The same, for a parameter that defaults to None |
| `BUG-MISSING-RETURN` | A function returns a value on some paths and falls off the end on others |
| `BUG-DIV-BY-LEN` | Division by `len(x)` or a numeric parameter with no check before it |
| `BUG-OFF-BY-ONE` | `x[len(x)]`, `range(len(x) + 1)`, or `x[i + 1]` over the whole of `x` |
| `BUG-MUTATE-WHILE-ITERATING` | A collection changed by the loop that iterates over it |
| `BUG-INFINITE-LOOP` | `while True` with no break, return or raise of its own, or a `while` whose condition names nothing the loop changes (`static_analysis/loop_checks.py`; conservative: a name passed to a call counts as changed) |

The None check is a may-analysis. It tracks which locals may be None, narrows that along branch
edges (`if x`, `is None`, `isinstance`, `and` / `or`, `assert`) and respects short-circuit evaluation.
These checks are hints, not proof: they cannot see what callers really pass. `FlowAnalyzer` is not in
`default_analyzers()`, so saved Code Review baselines stay comparable.

### What each finding carries

Besides the shared fields (ID, category, title, description, file, lines, evidence, severity,
confidence, recommendation), every finding has:

- `snippet`: the finding's own lines, read from the file (never from the LLM);
- `evidence_basis`: `static_confirmed` (a rule produced or agreed with it), `llm_with_context` (the
  LLM cited retrieved context it was really shown, listed in `context_refs`) or `llm_inferred`
  (the LLM alone). It is provenance, not a probability (D33);
- `bug`: bug type, root cause, trigger, expected and actual behaviour, repro steps (suggested, never
  run), involved names and `fix_explanation` (why the fix removes the bug).

The agent never runs the analyzed code, so no finding claims it was executed. Guidance is retrieved
from `bug_patterns.md`, `error_handling_testing.md` and `security_owasp_cwe.md` only (D34). It runs on
Gemini or, for development, on a local Ollama model (docs/llm-ollama.md).

### Claim checks

On top of normal evidence validation, an LLM bug is rejected if it names no trigger, or if an
identifier it depends on is not in the code it cites. Rejections are counted by reason in
`stats["llm_rejected_by_reason"]`.

### Budget

Each review unit is one LLM request, and the free tier allows few. A scan ranks units by static
signals and branching, reads the top `bugs.max_units`, and reports how much it did not read, in
`stats["scan_coverage"]`, in the report and on the command line. Unread code keeps its static
findings.

### Localization

1. **Candidates**, from reading the test: functions it names, what they call up to three levels down,
   the rest of the files that reaches, and the module the test file is named after. Configuration D
   adds retrieval. Test files are never candidates.
2. **Static order**: call distance, then rules that fired in the function.
3. **LLM re-ranking** of the top candidates that fit `bugs.max_prompt_chars`. Its reply can only
   reorder the list: a reference that is not in the list is dropped. If it ranks nothing, the run
   keeps the static order and records `llm_failed`.

## Evaluation

```bash
python -m marl_agents.cli eval-bugs audit --split dev           # which bugs are usable; no LLM
python -m marl_agents.cli eval-bugs localization --split dev --limit 10 --config configs/gemini.yaml
python -m marl_agents.cli eval-bugs detection    --split dev --limit 10 --config configs/gemini.yaml
python -m marl_agents.cli eval-bugs detection --split test --limit 30 --final --config configs/gemini.yaml
python -m marl_agents.cli eval-bugs labels --split test --limit 30   # blank bug-type sheet
```

**Running over several days.** Run the same command again. Finished samples are kept in a ledger
under `data/cache/bugsinpy/ledger/`, keyed by task, split, seed, model, prompt versions and harness
version. Each command saves a run with everything finished so far and says how much is left. A
quota stop, `--max-llm-calls` or a full disk all stop between samples. A prompt change starts a new
ledger, so numbers from two prompts cannot mix.

### Why two tracks

| Track | Input | Metrics |
|---|---|---|
| Localization | The failing test's source, and the repository at the buggy commit | Top-1/3/5 for function and file, MRR |
| Detection | One changed function, buggy and fixed, in separate requests | Precision, recall, F1, AUC, discrimination |

**A repository scan cannot measure precision on BugsInPy.** It labels one bug per commit, so a finding
that matches no label is not proven false. Detection therefore uses each bug's fixed function as its
negative. Both versions get the same project around them; only the patched file differs.

A localization suspect counts if it is a gold function or contains a fixed line. A closure sits
inside the function that defines it, so naming the outer function points at the right code.

- *Any defect in the function*: a finding anywhere in the function counts.
- *Defect at the fixed lines*: on the buggy function, the finding must be within 2 lines of a change.
  On the fixed function, any finding is a false positive.
- *Discrimination*: the share of bugs flagged on the buggy function only. A tool that flags everything
  scores 0, however high its recall.

### Configurations

| | Static | LLM | RAG |
|---|---|---|---|
| A `static_only` | yes | no | no |
| B `llm_only` | no | yes | no |
| C `static_llm` | yes | yes | no |
| D `static_llm_rag` | yes | yes | yes |

Without any candidates there is nothing to rank, so the call-graph walk runs in every localization
configuration. "RAG" there means retrieval adds candidates. In detection, "RAG" means the
`ContextBuilder`, as in the Code Review Agent (D25). See D31.

### Rules that protect the numbers

- **Split.** Dev and test share no project (`DEV_PROJECTS`). The test split needs `--final`.
- **Pool.** One source file, at most 10 changed lines, change inside a function. Results apply to such
  bugs only. Sampling is round-robin by project, since pandas alone is a third of BugsInPy.
- **No leakage.** The repository is taken at the buggy commit. Fetches are shallow, so later history is
  not on disk. Changed lines are never marked in a prompt (`function_scope`).
- **Failing test as input.** It comes from the fixed commit, as is standard for fault localization. It
  may name the function under test, which is why the static and random baselines are reported.
- **Failures count.** A failed sample is a miss in localization and a wrong answer in detection (D22).
- **Ceiling.** `gold_shown_to_llm` says how often the gold function reached the LLM at all.
- **Safety.** Project code is never run. Archives are read member by member: only regular files, inside
  the target, with reviewable extensions. Commit ids, project names and URLs are validated before
  reaching git, and fetching stops if disk space falls below 3 GB.

### Bug-type labels

BugsInPy has no bug types. Two people each fill in a copy of the sheet from `eval-bugs labels`,
separately and before seeing results. Pass both with `--bug-types a.csv,b.csv`: the comparison run
reports Cohen's kappa and top-1 by type, on the bugs where the two agree.

## Not built

- **Repro confirmation (Track 3).** Checking that a generated test fails on the buggy code and passes on
  the fix needs each project's old environment, in Docker. `repro_steps` are therefore suggestions,
  and reports say they were not run.
- **Fig. 3 stages 7 and 8 (bug-report store, learning loop).** Runs and reports are saved, and a fix can
  be re-checked with `review-change`, but nothing learns from feedback, and there is no past-issue
  data to retrieve. These are future work and should be described that way.
- **Commit-history retrieval.** Fig. 3 lists it. An uploaded ZIP has no history, and on BugsInPy it
  would need care not to leak the fix.
- **Concurrency checks.** The LLM may report these; no static rule looks for them.
