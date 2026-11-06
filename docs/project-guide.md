# Project Guide: Multi-Agent AI Assistant for Software Engineering

Team 23UG082 (23CSE399). Guide: Ms. Shalini Tiwari.

This document explains what we built, how the code works, which file does what, and where each idea
came from. Read sections 1 to 3 for the big picture, section 4 and 5 for the logic, section 9 for
the file map, and section 11 to prepare for questions from the panel.

---

## 1. The project in one page

**Goal.** Build a platform where five specialised AI agents analyse a software repository:

| Agent | What it does | Status |
|---|---|---|
| Code Review | quality, bugs, security smells, maintainability, review comments | **Complete (Phase 1)** |
| Bug Detection | logic/runtime errors, where they are, how to reproduce | next phase |
| Security | vulnerabilities, OWASP Top 10, CWE mapping | next phase |
| Test Generation | unit tests and edge cases | next phase |
| Documentation | missing or outdated docstrings and docs | next phase |

Every agent gets **project-specific context** from a RAG layer (Retrieval-Augmented Generation).
LangGraph will run the agents together, and a Result Aggregator will merge their output.

**What makes it more than "ask ChatGPT to review my code":**

1. **It never trusts the LLM blindly.** Every finding must point at real lines and quote code that
   really exists there; otherwise it is rejected.
2. **It combines rule-based tools with the LLM.** Ruff, Radon, mypy and our own AST checks find
   what rules can find, reliably and for free. The LLM finds what rules cannot (logic errors,
   design problems) and confirms or disputes the tool findings.
3. **It understands the whole repository, not one file.** A call graph tells it who calls a
   function. That is how it notices that a change in one file breaks code in another.
4. **It is measured honestly.** Every number comes from a saved benchmark run, including the
   ones where our first idea failed.

**Phase 1 result.** The Code Review Agent is finished. It works on a whole repository and on a code
change (a pull request), and it is usable from a web dashboard, the command line, a git
pre-commit hook and CI. The shared building blocks (ingestion, parsing, RAG, findings pipeline,
reports, evaluation) are ready for the other four agents.

---

## 2. What we built (features)

**Reviewing code**
- Inputs: a repository folder, a ZIP, a single `.py` file, or pasted code.
- Static analysis: Ruff (lint and security rules), Radon (complexity), custom AST checks,
  secret detection, test-gap detection, and mypy type checks.
- An LLM review of each function-sized unit, with project context.
- Every finding carries severity, category, evidence, a recommendation, a test suggestion and a
  CWE id where relevant.
- **Verified fix suggestions.** A patch is shown only if it passes re-analysis, and it is never
  applied automatically.

**Reviewing a change (pull-request review)**
- Inputs: git `base..head`, uncommitted work, staged work (before a commit), or two ZIPs.
- **Breaks outside the diff:** callers that the change did not touch but which no longer fit it.
- **"Review these hunks first":** every changed block is ranked by risk.
- A short PR-style summary written by the LLM.

**Where you can use it**
- Web dashboard (React + FastAPI): upload, live progress, charts, findings, diffs, reports.
- Command line: `review`, `review-change`, `eval`.
- Git pre-commit hook: blocks a commit with high-severity findings.
- CI (GitHub Actions example): SARIF output shows findings as annotations on the pull request.
- Reports in JSON, Markdown, PDF and SARIF.

**Evaluation**
- Benchmarks: CodeReviewer (both tasks), a planted-issue repository, and a RAG retrieval test.
- Usefulness: a blind LLM judge plus a kit for human ratings.
- Every run is saved with its config, model, prompts, sample IDs and raw predictions.

---

## 3. How a review works: the big picture

```
 Input (folder / ZIP / file / snippet)
   |
   v
 1  Ingestion ............ safe extraction, filter files, never execute code
 2  Parsing .............. Python AST -> functions, classes, imports, call graph
 3  Static analysis ...... Ruff, Radon, AST checks, secrets, test gaps, mypy
 4  Review units ......... split code into function/class-sized pieces (max 200 lines)
 5  Context .............. callers/callees/tests (call graph) + similar code (ChromaDB)
                           + OWASP / Python-standards guidance
 6  LLM review ........... prompt = code + static hints + context -> JSON findings
 7  Validation ........... evidence must exist at the cited lines (repair or reject)
 8  Actionability ........ drop vague findings
 9  Dedup ................ merge the same issue found by Ruff and the LLM
10  Severity rubric ...... severity set by rules, not by the LLM
11  Confidence ........... ranking score; filter below 0.3 (critical always kept)
12  Redaction ............ mask secrets in evidence
13  Verified fixes ....... Ruff autofix + LLM patches, re-analysed before shown
14  Reports .............. JSON / Markdown / PDF / SARIF + dashboard numbers
```

**A worked example** with `examples/order_service.py`, a file with deliberate problems:

- **Ruff** flags `yaml.load` without a safe loader (S506), `subprocess(..., shell=True)` (S602) and
  a mutable default argument `def f(x=[])` (B006).
- **The AST checks** flag a bare `except: pass` that swallows errors.
- **The secret scanner** flags an API key written in the code. The key is masked in the report.
- **The LLM** sees each function with its callers and similar code. It adds a SQL-injection
  finding (an f-string inside a query) and confirms the static findings.
- **Validation** checks each LLM finding's quoted line really exists. When Ruff and the LLM flag
  the same issue on overlapping lines, dedup merges them into one finding with both sources. The
  rubric sets severities and the findings are ranked.
- **Fixes:** for B006, Ruff offers an autofix, shown as a diff.

---

## 4. The logic, stage by stage

Each stage is its own Python package with a small interface, so stages can be tested and swapped
on their own.

### 4.1 Ingestion (`ingestion/`)
- Uploaded code is **untrusted**. It is read as text and never run, imported or installed.
- **ZIP safety** (`safe_zip.py`):
  - rejects "zip-slip" paths (`../../etc/passwd`), absolute paths and symlinks;
  - limits the total size (100 MB compressed, 500 MB uncompressed), the file count (20,000) and
    the per-file size (2 MB).
- **Filtering:** only text extensions are kept (`.py .md .yaml .json .toml ...`), and folders like
  `.git`, `venv`, `node_modules` and `dist` are skipped.
- **The `Repository` object** (`models.py`) reads files lazily and caches them.
- **Line-ending fix:** files are written with LF line endings so line numbers stay exact on
  Windows. (A bug we found and fixed: CRLF translation was doubling line numbers.)

### 4.2 Parsing and the call graph (`parsing/`)
- `python_ast.py` uses Python's own `ast` module to list functions, classes, methods, imports
  and calls, with exact line ranges. Parsing never executes the code.
- `repo_index.py` builds a **repository-wide index**: a symbol table, a call graph (who calls
  whom) and test references (which tests mention which function).
- This index is what lets the agent reason about other files: "this function has 3 callers".

### 4.3 Static analysis (`static_analysis/`)
- Every analyser returns the same `Finding` schema (`base.py`).
- **Ruff** runs as a subprocess with an argument list, a timeout and our own settings, so the
  repository's configuration can never run code.
- **Radon** measures cyclomatic complexity and maintainability.
- **AST checks** (`ast_checks.py`) cover what the tools miss:
  - swallowed exceptions;
  - resource leaks (`open()` without `with`);
  - deep nesting, long functions, too many parameters, missing docstrings;
  - **secrets** (API keys, passwords);
  - **test gaps** (modules or functions that no test references).
- **mypy** (`type_check.py`) catches type errors at call sites, for example passing the wrong
  argument type. It runs with our own empty config, so repository plugins are never loaded.
- **The rule table** (`rules.py`) maps each rule id to category, severity, prior confidence,
  CWE and default fix. **The table decides severity, not the LLM.**

### 4.4 Review units (`agents/code_review/units.py`)
The LLM reviews **units** of at most 200 lines, aligned to function and class boundaries. Small
neighbouring pieces are merged. This keeps each prompt focused and inside the model's limits.

### 4.5 Context: the RAG layer (`agents/code_review/context.py`, `rag/`)
The prompt gets context from three sources, in this priority order, under a 12,000-character
budget:
1. **Structural** (from the call graph): callees defined elsewhere, callers, and tests of the
   unit. This is precise and explainable.
2. **Retrieved** (dense retrieval): similar code chunks from the vector store (ChromaDB).
3. **Guidelines:** matching sections of our knowledge base (`rag/knowledge/*.md`), which covers
   OWASP/CWE security, Python standards, and error handling and testing.

Supporting files:
- `chunking.py` makes one chunk per function, method or class, and splits docs by heading.
- `embeddings.py` provides two embedders: an offline **hashing** embedder (the default; no
  download) and a neural sentence-transformers embedder. Comparing them is part of the evaluation.
- `store.py` provides an in-memory store (tests) and ChromaDB (persistent).
- RAG can be switched off (`rag.enabled: false`). That is configuration B of the planned system
  experiment.

### 4.6 LLM review (`agents/code_review/agent.py`, `prompts/`, `llm_schema.py`)
- **Prompts** are versioned files (`prompts/system.md`, `review.md`, ...), not strings in code.
  Every result records the prompt version.
- The prompt contains:
  - the numbered code (changed lines are marked in change review);
  - the static findings for that unit, for the LLM to *confirm* or *dispute*;
  - the context.
- Code is wrapped as **data**, and the prompt says that instructions inside code are not to be
  followed. This is our defence against prompt injection.
- The LLM must answer in **JSON matching a schema** (Pydantic). If the JSON is invalid, it is
  asked once more with the error. `llm_schema.py` parses leniently, so one broken finding does
  not discard the others.
- **Request too large:** if a unit plus its context exceeds the model's per-request limit, the
  unit is retried once without the retrieved context. The code itself is never dropped.
- Units are reviewed concurrently. Token usage is counted per review.

### 4.7 Validation (`findings/validation.py`)
**Validation is the most important safety step.** An LLM finding is accepted only if:
- the file exists in the repository;
- the line range is inside the file;
- the quoted **evidence really appears** at those lines (whitespace-insensitive).

If the evidence is found a few lines away, the finding is **repaired** (moved) and its
confidence is lowered. Otherwise it is **rejected and counted**. The rejection rate is reported,
so hallucinations are measured, not hidden.

### 4.8 Actionability filter (`findings/actionability.py`)
Industrial studies (see references) say developers ignore review bots that give vague advice. An
LLM-only finding is checked for four problems:
- vague wording ("consider improving", "make sure") without a concrete code reference;
- no concrete fix;
- a question instead of a stated problem;
- a missing explanation.

**Two or more problems drop the finding. One problem downgrades it to `info`.**

### 4.9 Deduplication (`findings/dedup.py`)
- When the same issue is found twice (for example a bare `except` flagged by Ruff and by the LLM),
  the findings are merged.
- Merging requires the same file, overlapping lines and a compatible category; then the
  descriptions are compared.
- The merged finding keeps both sources (`sources: ["ruff", "llm"]`), which also raises
  confidence.
- Findings in different files are merged only when one points at the other, as an impact finding
  does.

### 4.10 Severity rubric (`findings/severity.py`, `docs/severity-rubric.md`)
Severity levels are critical, high, medium, low and info.
- Tool findings take their severity from the rule table.
- LLM findings only *propose* a severity. The rubric then applies floors and caps per category.
  For example, a style issue can never be "critical".

### 4.11 Confidence and ranking (`findings/confidence.py`)
Confidence is a **ranking signal from 0 to 1, not a probability.**
- **Starting value:** tool findings start from the rule's prior reliability.
- **LLM-only findings:** confidence × 0.8, capped at 0.9, because LLMs are over-confident.
- **Repaired** by the validator: × 0.85.
- **LLM disputes** a static finding: × 0.5.
- **LLM confirms** a static finding: combined as an independent vote, `1 - (1 - c)(1 - 0.3)`.
- **Ranking:** priority = severity rank + confidence, so severity dominates and confidence breaks
  ties.
- **Filter:** findings below 0.3 are dropped, but **critical findings are always kept**.

### 4.12 Redaction (`findings/redaction.py`)
Secrets found in code are masked in the evidence, so reports never re-publish a password.

### 4.13 Verified fix suggestions (`agents/code_review/fixes.py`, `core/fixes.py`)
- **Ruff autofix:** "safe" fixes are marked verified. "Unsafe" fixes (they can change behaviour)
  are marked "review before applying".
- **LLM fix** (medium-or-higher findings, at most 8 per review). The LLM proposes a replacement
  for a line range, then the patch must pass every check:
  1. stay inside the finding's region;
  2. parse as Python;
  3. on re-analysis (Ruff, AST checks, secrets), introduce **no new issue**;
  4. for a tool-detected issue, make that issue **disappear**. Only then is it "verified".
     Otherwise it is "suggested".
- Rejected fixes are counted by reason. **Fixes are never applied to the user's code.**

### 4.14 Reports and dashboard numbers (`reports/`)
- **Formats:** JSON (everything), Markdown, PDF (ReportLab) and SARIF 2.1.0, the standard format
  GitHub code scanning reads.
- **Dashboard numbers:** finding counts by severity and category, and the **issue density**,
  `(10*critical + 5*high + 2*medium + 0.5*low) per 1,000 reviewed lines`. (An earlier 0-100
  "quality index" was removed: it was a heuristic score with no ground truth to validate it.)

---

## 5. Change (pull-request) review logic

Code lives in `ingestion/changes.py` and in `agents/code_review/` (`change_review.py`,
`impact.py`, `risk.py`, `change_summary.py`).

### 5.1 Reading the change safely
- **From git:** git's raw plumbing commands (`ls-tree`, `cat-file --batch`) read files straight from
  the git database. There is no checkout, and hooks and filters are disabled. Branch names are
  validated, so input like `--upload-pack=...` is rejected.
- **From two ZIPs:** both are extracted safely.
- **The diff:** computed with `difflib`. Renames are detected by similarity of 85% or more.
- **The `ChangeSet`** holds the old and new versions plus each file's changed line ranges.

### 5.2 Impact analysis: "breaks outside the diff" (`impact.py`)
For every function the change added, modified or removed, find all its call sites (call graph)
and check them:
- **`IMPACT-REMOVED`:** a removed function is still called somewhere.
- **`IMPACT-SIGNATURE`:** a call no longer matches the new signature, for example a new required
  parameter. This is checked the same way Python binds arguments: missing required, too many
  positional, unknown keyword. Calls with `*args` are not judged, so no guessing.
- **`IMPACT-BEHAVIOR`** (LLM): the LLM sees the old version, the new version and the untouched
  callers, and reports behaviour changes such as "now returns None for a missing user". These
  findings are validated like all LLM findings.
- **`TYPE-*`** (mypy): type errors at call sites in the impacted files.

A reviewer who reads only the diff cannot see these.

### 5.3 Scoped review
The normal pipeline (section 4) runs, but only **changed lines** produce findings. Impact
findings join before dedup, the rubric and ranking.

### 5.4 Hunk risk: "review these hunks first" (`risk.py`)
Every changed block (hunk) gets a score:

`score = 100 * sigmoid(logit)`, read as the **estimated chance (%) that a reviewer would comment on
this hunk.**

| Signal | Weight (logit) | Source |
|---|---:|---|
| starting value (intercept) | -0.318 | calibrated |
| touches security-sensitive code (eval, pickle, subprocess, SQL, secrets...) | +0.454 | calibrated |
| changes error handling (try/except/raise) | +0.648 | calibrated |
| changes a function signature | +0.234 | calibrated |
| size: per doubling of changed lines | +0.055 | calibrated |
| breaks call sites in other code | +1.0 each, max +2.0 | expert-set |
| changed public function has no test | +0.3 | expert-set |

- **Levels:** high ≥ 59.7, medium ≥ 47.4, otherwise low.
- **Guardrail:** a hunk with a critical finding is always "high", and one with a high finding is at
  least "medium".

**How the weights were found (an honest story worth telling the panel):**
1. **Version 1** used hand-picked points. On CodeReviewer's test set it ranked **worse than
   chance** (AUC 0.434). Static findings, its biggest signal, did not predict where humans
   commented.
2. **Version 2:**
   - We fixed the inputs in advance.
   - We fitted four weights with logistic regression on the **validation** split only
     (`scripts/calibrate_hunk_risk.py`).
   - We dropped signals with zero or negative weight, because a signal must never *lower* risk.
   - We then tested **once** on the test split.
3. **Result** (re-run on 2026-10-12, after a line-ending bug fix; see `docs/results.md` 6a): of the
   10% of hunks v2 ranks first, **73.3%** received a human comment, against 30.5% for v1 and
   48.4% at random. Ranking by **size alone does slightly better (79.2%)**. v2 was fitted on
   validation data that had the same bug, so re-fitting it on corrected validation data is the
   documented next step.

### 5.5 Summary and outputs
- The LLM writes a 3-5 sentence PR summary (`change_summary.py`).
- **Outputs:**
  - **CLI exit code:** `--fail-on high` returns 1, which blocks CI or a commit.
  - **SARIF:** annotations on GitHub pull requests.
  - **Dashboard:** a diff view of the risk-ranked hunks.

---

## 6. The LLM layer (`llm/`)

- **One interface** (`base.py`): `LLMProvider.generate(...)` and `generate_structured(...)`. No
  other package imports a vendor SDK, so changing the model is a config change.
- **Providers:**
  - `gemini.py`: Google Gemini through the free tier, the default (decision D27);
  - `openai_compat.py`: Groq, OpenAI, Ollama, vLLM;
  - `mock.py`: a fake LLM for tests, so the backend tests run **without an API key**.
- **Model:** `gemini-3.8-flash` by default. `cli models` lists what your key can use, and `cli check`
  tests the key and suggests a replacement if the model is unavailable. Setup, limits and the
  free-tier privacy warning are in [llm-gemini.md](llm-gemini.md).
- **Free-tier quotas** (`rate_limit.py`, decisions D21 and D27):
  - a client-side limiter (requests and tokens per minute) and a daily budget kept on disk;
  - each failure is classified: a per-minute limit waits as the server says, a daily quota stops at
    once, an oversized prompt is retried without context, and other errors back off a bounded
    number of times;
  - after a quota stop the remaining units make no calls, the review ends **partial**, and a rerun
    or the dashboard's Resume button continues it without repeating finished units
    (`agents/code_review/scheduling.py`);
  - a partial review is flagged in the dashboard, the CLI and the performance record.
- **Change classifier** (`classifier.py`, decision D28): a fine-tuned code model that orders or gates
  LLM work in change reviews. It can never remove a finding. See [fine-tuning.md](fine-tuning.md).
- Temperature 0 and seed 42, for reproducibility.

---

## 7. The web application

### Backend (`api/`)
- **`app.py`** is the FastAPI server. Routes:
  - `/api/reviews` (upload, list, get, delete, download reports);
  - `/api/changes` (change review);
  - `/api/llm/status` and `/api/llm/models`;
  - `/api/experiments` (evaluation results).
  The same server also serves the built React app.
- **`jobs.py`** runs reviews in the background (2 at a time) and saves each one under
  `data/jobs/<id>/`, so history survives restarts. Uploaded code is deleted after its review.
- **Security:** a local git repository can be read only by the dashboard on the same machine. This
  needs three things:
  - a request from loopback (the same computer);
  - a loopback Host name, which blocks "DNS rebinding";
  - an `X-Marl-Client` header, so other websites cannot trigger it.

### Frontend (`frontend/src/`)
- **Stack:** React 19, TypeScript, Tailwind CSS and Vite, tested with Vitest (39 tests).
- **Pages:**
  - **New review:** upload, paste code, or review a change; choose the mode and model.
  - **Review:** progress, summary tiles, charts, findings, change panel and fix diffs.
  - **History.**
  - **Evaluation:** all saved benchmark runs.
- **Charts** follow accessibility rules: an ordinal colour ramp for severity, plus a table view
  and tooltips.

---

## 8. Evaluation

### Datasets (in `capstone-datasets/`, read-only)

| Dataset | Used for | Note |
|---|---|---|
| CodeReviewer | Code Review Agent | multi-language; we filter to Python |
| BugsInPy | Bug Detection (next phase) | needs per-bug checkout |
| Devign | Security (next phase) | C code, not Python |
| HumanEval | Test Generation (next phase) | 164 problems |
| CodeSearchNet | Documentation (next phase) | code-comment pairs |
| SWE-bench Lite | whole system (next phase) | resolve rate |

### What we measured and the main results

| Question | Benchmark | Result |
|---|---|---|
| Does it find planted defects? | 17 hand-labelled issues + a clean control file | static: recall 0.941 (16/17), precision 1.0; with the LLM: recall 1.0, precision 1.0 |
| Does this hunk need a comment? | CodeReviewer cls, 4,195 Python hunks | static only, cross-hunk rules excluded: precision 0.592, AUC 0.539 |
| Does "review first" rank well? | CodeReviewer cls (valid: fit, test: once) | top 10%: 73.3% commented (v1 30.5%, random 48.4%; size alone 79.2%) |
| Does it write review comments? | CodeReviewer msg, the same 36 samples | coverage 0.78 vs 0.47 static; chrF 13.6 vs 8.7; BLEU not significantly different |
| Are the comments useful? | blind LLM judge (gpt-oss-20b) | agent 4.71 / 4.64 vs human 3.67 / 3.00 (relevance / informativeness); **preliminary, see caveats** |
| Does RAG find related code? | call-graph relevance, 277 queries | recall@10 0.438 vs 0.030 random; MRR 0.354 vs 0.037 |

Details, run IDs and caveats are in `docs/results.md`.

### Integrity rules we follow (`.claude/rules/evaluation-integrity.md`)
- Every number comes from a saved run, with its config, model, prompt versions, sample IDs and
  raw predictions.
- Benchmark answers are never put in the RAG index.
- Test splits are not used for tuning. The hunk-risk weights were fitted on validation only.
- Failures are counted, not hidden. For example, samples where the LLM failed (quota) are excluded
  and reported.
- Metrics have unit tests with hand-computed values.

---

## 9. Project files: what each one does

### Top level

| Path | Purpose |
|---|---|
| `CLAUDE.md` | project rules and overview for the AI assistant and contributors |
| `README.md` | quick start |
| `pyproject.toml` | Python package, dependencies, Ruff/mypy/pytest settings |
| `configs/default.yaml`, `configs/gemini.yaml`, `configs/groq.yaml` | all settings (secrets only in `.env`) |
| `.env.example` | template for API keys (never commit `.env`) |
| `docs/` | documentation (this file, results, decisions, rubric, datasets, dashboard) |
| `experiments/results/` | one folder per saved evaluation run |
| `examples/` | `order_service.py` (sample with bugs), CI workflow example |
| `scripts/` | dashboard starter, pre-commit hook + installer, risk calibration |
| `frontend/` | React dashboard |
| `tests/` | 289 automated backend tests |
| `PPT/` | presentations |
| `capstone-datasets/` | benchmark data (~11 GB, read-only, not in git) |

### `src/marl_agents/` (the Python package)

**Core and configuration**

| File | Purpose |
|---|---|
| `core/schemas.py` | shared data models: `Finding`, `Severity`, `Category`, `ReviewResult`, `ChangeReview`, `SuggestedFix` |
| `core/fixes.py` | text edits and unified diffs for fix suggestions |
| `config.py` | loads YAML config + `MARL_` environment variables |
| `cli.py` | command line: `review`, `review-change`, `eval`, `models`, `check`, `serve` |

**Ingestion**

| File | Purpose |
|---|---|
| `ingestion/loader.py` | folder / ZIP / snippet / in-memory files -> `Repository` |
| `ingestion/safe_zip.py` | zip-slip, symlink and zip-bomb protection |
| `ingestion/models.py` | `Repository` (lazy, cached file access) |
| `ingestion/diff.py` | parse unified diffs, apply a hunk (used by the CodeReviewer evaluation) |
| `ingestion/changes.py` | `ChangeSet` from git refs, working tree, staged changes, or two ZIPs |

**Parsing and RAG**

| File | Purpose |
|---|---|
| `parsing/python_ast.py` | functions, classes, imports and calls from the AST |
| `parsing/repo_index.py` | symbol table, call graph, test references |
| `rag/chunking.py` | code-aware chunks (one per function/class) |
| `rag/embeddings.py` | hashing embedder (offline) + sentence-transformers |
| `rag/store.py` | in-memory and ChromaDB vector stores |
| `rag/retriever.py` | index a repository, retrieve similar chunks and guidelines |
| `rag/knowledge/*.md` | OWASP/CWE, Python standards, error-handling guidance |

**Static analysis**

| File | Purpose |
|---|---|
| `static_analysis/base.py` | common analyser interface |
| `static_analysis/ruff_analyzer.py` | Ruff subprocess + autofix diffs |
| `static_analysis/radon_analyzer.py` | complexity / maintainability |
| `static_analysis/ast_checks.py` | custom checks, secrets, test gaps |
| `static_analysis/type_check.py` | mypy, with plugins disabled |
| `static_analysis/rules.py` | rule id -> category, severity, confidence, CWE |

**Findings pipeline**

| File | Purpose |
|---|---|
| `findings/validation.py` | evidence check, repair, rejection |
| `findings/actionability.py` | drop / downgrade vague findings |
| `findings/dedup.py` | merge duplicates across sources and files |
| `findings/severity.py` | severity rubric |
| `findings/confidence.py` | confidence calibration and ranking |
| `findings/redaction.py` | mask secrets |

**The Code Review Agent**

| File | Purpose |
|---|---|
| `agents/base.py` | contract every agent follows (`run(request) -> result`) |
| `agents/code_review/agent.py` | **the main pipeline** (sections 4.1-4.14) |
| `agents/code_review/units.py` | split files into review units |
| `agents/code_review/context.py` | build the prompt context |
| `agents/code_review/llm_schema.py` | the JSON the LLM must return, lenient parsing |
| `agents/code_review/fixes.py` | verified LLM fix generation |
| `agents/code_review/change_review.py` | change review orchestration |
| `agents/code_review/impact.py` | breaks outside the diff |
| `agents/code_review/risk.py` | hunk risk model v2 |
| `agents/code_review/change_summary.py` | central change + LLM PR summary |
| `agents/code_review/node.py` | adapter for LangGraph (next phase) |
| `agents/code_review/prompts/*.md` | versioned prompts: system, review, impact, summary, fix |

**LLM, reports and web API**

| File | Purpose |
|---|---|
| `llm/base.py` | `LLMProvider` interface, structured output, usage counting |
| `llm/openai_compat.py` | Groq / OpenAI-compatible provider, quota handling |
| `llm/rate_limit.py` | requests/tokens-per-minute limiter |
| `llm/gemini.py`, `llm/mock.py`, `llm/factory.py` | Gemini, test mock, provider selection |
| `reports/renderers.py` | JSON / Markdown / PDF reports |
| `reports/sarif.py` | SARIF 2.1.0 export |
| `reports/summary.py` | dashboard numbers (counts, issue density) |
| `api/app.py` | FastAPI routes |
| `api/jobs.py` | background review jobs |

**Evaluation**

| File | Purpose |
|---|---|
| `evaluation/datasets/codereviewer.py` | CodeReviewer loader, Python filter, seeded sampling |
| `evaluation/metrics/*.py` | classification (AUC, F1, bootstrap CI), text (BLEU, ROUGE-L, chrF), retrieval, detection, agreement (kappa, Spearman) |
| `evaluation/runners/code_review.py` | CodeReviewer, planted, retrieval runners |
| `evaluation/runners/change_risk.py` | hunk-risk evaluation |
| `evaluation/runners/usefulness.py` | LLM judge, human rating kit, agreement |
| `evaluation/calibration.py` | logistic regression used for the risk weights |
| `evaluation/recorder.py` | saves every run (config, git commit, predictions, metrics) |
| `evaluation/prompts/usefulness.md` | judge prompt |
| `orchestration/` | LangGraph graph (next phase) |

### `frontend/src/`

| File | Purpose |
|---|---|
| `api/client.ts`, `api/types.ts` | calls to the backend, typed like the Python models |
| `pages/NewReview.tsx` | upload / paste / change review form |
| `pages/ReviewDetail.tsx` | review dashboard |
| `pages/History.tsx`, `pages/Evaluation.tsx` | history, benchmark runs |
| `components/FindingsTable.tsx` | filterable findings with evidence and fix diffs |
| `components/ChangePanel.tsx`, `components/DiffView.tsx`, `components/ChangeForm.tsx` | change review UI |
| `components/HBarChart.tsx`, `components/StatTile.tsx`, `components/ui.tsx`, `components/Layout.tsx` | charts and UI parts |
| `test/*.test.tsx` | 39 frontend tests |

### `tests/`
- `unit/...` mirrors the package layout (one test file per area).
- `integration/` tests the whole agent and the API end to end.
- `fixtures/repos/planted/` is the planted-issue repository; `planted_expected.json` is its answer
  key.

---

## 10. References: where the ideas came from

All code in this repository was written for this project. **No code was copied from the papers
or from other projects.** External tools (Ruff, Radon, mypy, ChromaDB, FastAPI, React and others)
are used as libraries through their public interfaces. The sources below gave us **ideas,
methods, datasets and evaluation protocols.**

### Which idea came from which source

| What we built | Source of the idea |
|---|---|
| The tasks "does this change need a comment?" and "write the review comment"; the dataset; BLEU evaluation; relevance / informativeness criteria | Li et al., CodeReviewer (ESEC/FSE 2022) [1] |
| Change review, impact analysis (functions that must change together), salient / central change, usefulness over BLEU, actionable comments | Tufano & Bavota, SLR on code-review automation (2025) [2] (`docs/research/codereview.pdf`) |
| Adding retrieved project knowledge to the prompt | Lewis et al., RAG (NeurIPS 2020) [3] |
| Several specialised agents working together | Qian et al., ChatDev (ACL 2024) [4]; Hong et al., MetaGPT (ICLR 2024) [5] |
| System-level evaluation | Jimenez et al., SWE-bench (ICLR 2024) [6] |
| Security categories and the knowledge base | OWASP Top 10 [7]; MITRE CWE [8] |
| Datasets for the next agents | Devign [9], BugsInPy [10], HumanEval [11], CodeSearchNet [12] |
| LLM-as-a-judge, and its biases (length, self-preference) | Zheng et al. (NeurIPS 2023) [13] |
| Weighted kappa interpretation | Landis & Koch (1977) [14] |
| Smoothed BLEU, ROUGE-L, chrF | Lin & Och (2004) [15]; Lin (2004) [16]; Popović (2015) [17] |
| Bootstrap confidence intervals | Efron & Tibshirani (1993) [18] |
| SARIF output format | OASIS SARIF 2.1.0 [19] |

### Reference list
1. Z. Li et al., "Automating code review activities by large-scale pre-training," ESEC/FSE 2022.
2. R. Tufano, G. Bavota, "Automating Code Review: A Systematic Literature Review," arXiv:2503.09510, 2025.
3. P. Lewis et al., "Retrieval-augmented generation for knowledge-intensive NLP tasks," NeurIPS 2020.
4. C. Qian et al., "ChatDev: Communicative agents for software development," ACL 2024.
5. S. Hong et al., "MetaGPT: Meta programming for a multi-agent collaborative framework," ICLR 2024.
6. C. E. Jimenez et al., "SWE-bench: Can language models resolve real-world GitHub issues?," ICLR 2024.
7. OWASP Foundation, "OWASP Top 10," 2021.
8. MITRE, "Common Weakness Enumeration (CWE)."
9. Y. Zhou et al., "Devign: Effective vulnerability identification ... graph neural networks," NeurIPS 2019.
10. R. Widyasari et al., "BugsInPy: A database of existing bugs in Python programs," ESEC/FSE 2020 (demo).
11. M. Chen et al., "Evaluating large language models trained on code," arXiv:2107.03374, 2021 (HumanEval).
12. H. Husain et al., "CodeSearchNet challenge," arXiv:1909.09436, 2019.
13. L. Zheng et al., "Judging LLM-as-a-judge with MT-Bench and Chatbot Arena," NeurIPS 2023.
14. J. R. Landis, G. G. Koch, "The measurement of observer agreement for categorical data," Biometrics 33(1), 1977.
15. C.-Y. Lin, F. J. Och, "ORANGE: a method for evaluating automatic evaluation metrics for machine translation," COLING 2004.
16. C.-Y. Lin, "ROUGE: A package for automatic evaluation of summaries," ACL Workshop 2004.
17. M. Popović, "chrF: character n-gram F-score for automatic MT evaluation," WMT 2015.
18. B. Efron, R. Tibshirani, *An Introduction to the Bootstrap*, Chapman & Hall, 1993.
19. OASIS, "Static Analysis Results Interchange Format (SARIF) Version 2.1.0," 2020.

**Tool documentation we followed:**
- analysis tools: Ruff (rule codes, JSON output, fix safety), Radon, mypy;
- data and AI: ChromaDB, sentence-transformers, the Groq API (rate-limit headers, quotas);
- web stack: FastAPI, Pydantic v2, React, Vite, Tailwind CSS, ReportLab;
- language and git: the git plumbing commands (`ls-tree`, `cat-file`) and Python's `ast` module.

---

## 11. Questions the panel may ask (with short answers)

**Did you train a model?**
No. We use a pretrained LLM through prompting, RAG and static analysis. The only "fitting" is 4
weights of the hunk-risk score, found by logistic regression on validation data. That is
statistical calibration of a formula, not training a neural network (decision D17).

**How do you stop the LLM from hallucinating?**
Every LLM finding must quote code that exists at the lines it cites. Otherwise it is repaired or
rejected, and we report how many were rejected. Severity comes from rules, not from the LLM.

**Why use static tools if you have an LLM?**
Rules are free, fast and reliable for what they cover (security patterns, unused code,
complexity). The LLM covers logic and design. On the planted benchmark, static analysis alone
missed exactly the one logic bug (division by zero) that the LLM found.

**What does RAG add?**
Context from the rest of the project: callers, callees, tests, similar code, security
guidance. With it, the agent can tell that a change breaks a caller in another file. RAG can be
turned off to measure its effect (configuration B).

**Why is BLEU so low?**
A human reviewer writes one comment about one thing. A correct comment about a different real
issue scores almost zero. That is why we also measure coverage, chrF and usefulness (relevance and
informativeness), as the code-review literature recommends.

**Your first risk score was worse than random. Isn't that bad?**
We measured it, found out why (static findings do not predict human comments on this benchmark),
re-calibrated on validation data and tested once on test. Reporting the failure and the fix is
honest research practice. v2 puts human-commented hunks first 73% of the time, against 48% at
random. A plain size ranking does slightly better (79%), which we report openly; re-fitting v2 on
corrected validation data is the next step.

**Is the agent better than human reviewers?**
We do not claim that. The LLM judge rated the agent's comments higher, but agent comments are
about 7 times longer, and half of the human comments are questions, which the rubric penalises.
That needs human raters, and the rating kit is ready.

**Is it safe to upload any repository?**
Yes. Code is only parsed, never executed. ZIP extraction is protected, tools run with our own
settings, git is read without checkout or hooks, and secrets are masked in reports.

**What happens when the free LLM quota runs out?**
The system fails fast with a clear message ("daily quota reached, try again in N min, or choose
another model"). Static analysis still runs, and the result is clearly marked as partial.

**What is next?**
The other four agents reusing the same building blocks, LangGraph orchestration with the Result
Aggregator, and the SWE-bench Lite comparison: single LLM vs multi-agent vs multi-agent + RAG.

---

## 12. How to run

```bash
# setup (Windows, Python 3.11)
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,rag,llm,api,reports,analysis]"

# dashboard -> http://127.0.0.1:8000
powershell -ExecutionPolicy Bypass -File scripts\start-dashboard.ps1

# command line
python -m marl_agents.cli review examples/order_service.py
python -m marl_agents.cli review-change path/to/repo --base main --head feature --fail-on high
python scripts/install_hooks.py path/to/repo           # pre-commit gate

# tests (no API key needed)
pytest
cd frontend; npm test

# evaluations
python -m marl_agents.cli eval planted --mode static_only
python -m marl_agents.cli eval codereviewer --task cls --mode static_only
python -m marl_agents.cli eval hunkrisk
```

The LLM key goes in `.env` (`GROQ_API_KEY`), copied from `.env.example`.

---

## 13. Limitations and next steps

- **Python only** for code analysis.
- The impact analysis cannot resolve dynamic calls (`getattr`, `*args` forwarding). It skips them
  rather than guessing.
- **Free LLM tiers are limited.** Groq's allowed about 40 reviewed benchmark samples a day. Gemini's
  free limits depend on the model and project, so larger LLM evaluations may need several days;
  reruns continue where they stopped.
- **The usefulness result is preliminary** until two people complete the human rating kit.
- **Next phase:**
  - the four remaining agents;
  - LangGraph orchestration and the Result Aggregator;
  - SWE-bench Lite system evaluation (A / B / C);
  - a larger LLM run on CodeReviewer with the default model.

For deeper detail see `docs/code-review-agent.md` (design decisions), `docs/change-review.md`,
`docs/results.md` (all numbers with run IDs), `docs/decisions.md` (D1-D22) and
`docs/severity-rubric.md`.
