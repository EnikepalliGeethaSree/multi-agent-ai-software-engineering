# Dashboard

A web UI for the Code Review Agent: FastAPI backend (`src/marl_agents/api/`) + React, TypeScript and
Tailwind frontend (`frontend/`). The backend also serves the built frontend, so one process runs both.

## Start it

```powershell
# One command (creates the venv / builds the frontend if missing):
powershell -ExecutionPolicy Bypass -File scripts\start-dashboard.ps1
# -> open http://127.0.0.1:8000

# Or step by step:
cd frontend; npm install; npm run build; cd ..
python -m marl_agents.cli serve                    # add --port 9000, --host 0.0.0.0, --config configs\gemini.yaml
```

LLM settings come from `.env` (`LLM_PROVIDER=gemini`, `GEMINI_API_KEY`, `GEMINI_MODEL`), see
[llm-gemini.md](llm-gemini.md). Without a key the dashboard still works in **Static only** mode.

The **Performance** page shows each review's stage times, tokens and chunks, the active provider and
today's quota use, file size against execution time, benchmark history, and the original against the
improved system. Everything on it comes from saved reviews and runs; a value that was not measured
shows as "Unavailable". A partial review has a **Resume review** button on its page.

Frontend development with hot reload (API calls are proxied to :8000):

```powershell
python -m marl_agents.cli serve        # terminal 1
cd frontend; npm run dev               # terminal 2 -> http://localhost:5173
```

## Pages

| Page | What it does |
|---|---|
| **New review** (`/`) | Upload a `.zip` repository or a `.py` file, or paste code, or **review a change**: a local git repository (uncommitted work, staged changes, or two branches/commits) or two ZIP versions. Choose mode (Static + LLM, Static only, LLM only), model, RAG and call-graph context, test files, minimum confidence, and whether to suggest fixes (extra LLM calls). "Test connection" makes one tiny LLM call. |
| **Review** (`/reviews/:id`) | Live progress log while running. When done: stat tiles (findings, security, bugs, error handling, maintainability, testing gaps, files, issue density), charts (severity, category, most affected files), filterable/sortable findings with evidence, fix, test, CWE and validation audit trail, related locations and suggested-fix diffs (verified / review before applying); for a change review also "What changed" (narrative, impacted files), "Breaks outside the diff", the changed-functions table and risk-ranked hunks with diffs; a "partial review" warning when the LLM could not review some parts (quota, request too large); "How this review was produced" (LLM calls, tokens, hallucinations rejected, triage, timings); JSON / Markdown / PDF / SARIF downloads; delete. |
| **History** (`/reviews`) | All reviews with status, mode, model, findings, critical/high, duration. Auto-refreshes while something runs. |
| **Evaluation** (`/evaluation`) | The Code Review evaluation summary: the master comparison table (configurations A-D: Static Only, LLM Only, Static + LLM, Static + LLM + RAG, each with Static/LLM/RAG ticks) and one section per benchmark (planted issues, CodeReviewer classification raw/adjusted, comment generation, RAG vs random retrieval, risk vs size/random, efficiency, supplementary LLM judge). Each section shows its experiment conditions, fairness checks, N/A reasons with the command that produces a missing run, and metric definitions (formula, scale, direction) on hover. Below: all saved runs from `experiments/results/` with their configuration; each opens its summary, experiment configuration and raw `metrics.json`. |

Header: LLM status (provider/model ready, or why not), theme (system/light/dark).

## API

`http://127.0.0.1:8000/docs` has the interactive OpenAPI docs.

| Method | Path | |
|---|---|---|
| GET | `/api/health` | server status, job counts |
| GET | `/api/llm/status[?probe=true]` | provider, model, rate limits, ready/error (never the key); probe = one tiny call |
| GET | `/api/llm/models` | models available to the key (cached 10 min) |
| GET | `/api/reviews` | history |
| POST | `/api/reviews` | multipart: `file` (.zip/.py) **or** `snippet` + `snippet_name`; `options` JSON |
| GET | `/api/reviews/{id}` | job (status, progress, summary) + full result when done |
| GET | `/api/reviews/{id}/report/{json,md,pdf,sarif}` | download |
| POST | `/api/changes` | change review, multipart: `before` + `after` (.zip) **or** `repo_path` + optional `base`, `head`, `staged`; `options` JSON |
| DELETE | `/api/reviews/{id}` | delete a finished review |
| GET | `/api/experiments`, `/api/experiments/{name}` | evaluation runs |
| GET | `/api/evaluation/summary` | baseline comparison built from saved runs (configurations A-D, baselines, definitions) |

## Design notes

- Reviews run in a background thread pool (2 at a time) and are persisted to `data/jobs/<id>/`
  (`job.json`, `result.json`, reports). History survives restarts; a review interrupted by a restart is
  marked failed. Uploaded code is deleted as soon as its review finishes.
- One LLM provider per model is shared by all jobs, so the Groq rate limiter covers concurrent reviews;
  token usage is counted per review.
- A local git repository (`repo_path`) is read only for requests from this machine: loopback client,
  loopback `Host` (blocks DNS rebinding) and the `X-Marl-Client` header that the dashboard sends (a
  custom header forces a CORS preflight, so other websites cannot trigger it). Disable it with
  `create_app(allow_local_git=False)`; `/api/health` reports `local_git`.
- Uploads: `.zip` up to 100 MB (then safe extraction limits apply), `.py` up to 2 MB, file names
  sanitized, IDs validated; code is parsed, never executed.
- Charts follow the dataviz rules: severity uses an ordinal single-hue ramp validated for light and dark
  (`validate_palette.js --ordinal`), status colors appear only on badges with icon + label, every chart
  has a hover/focus tooltip and a table view, text never uses the data color.

## Tests

`pytest tests/integration/test_api.py tests/integration/test_api_changes.py` (API: every route, rejections, persistence, SPA hosting) and
`cd frontend; npm test` (components and pages with a mocked API). `npm run typecheck` checks types.

## Evaluation page layout

`/evaluation` is the summary: overview tiles, the status card, then seven numbered sections. Each card
keeps its table, status badges, warnings and a failed-or-missing line on screen. Fairness checks, source
runs, reproduction commands and failure details open from panels below it, and historical Groq timing
and the metric definitions open on request. The LLM judge is last, labelled supplementary.

`/evaluation/runs` is the complete history of saved runs, including runs that stopped before saving
metrics. A run that scored no samples shows Unavailable, and ROC-AUC is not shown below 30 samples. The
saved numbers stay in each run. "Unavailable" means not measured, and "N/A" means not applicable.

## Reading the Evaluation page

The status card at the top is worked out from the saved runs each time the page loads, so a new run
changes it without editing anything. A benchmark counts as complete only from its own `results.csv`.

- **Planted issues:** *Found* counts labelled issues of every category. *Correct* counts defect-class
  findings only. They are separate counts, so 17 found beside 14 correct is expected.
- **Paired comparisons:** below 30 paired samples a comparison is labelled preliminary and ROC-AUC is
  not reported. Saved scores stay in each run's `predictions.jsonl`.
- **Efficiency:** Gemini, static-only and historical Groq results are separate sections. Times use
  complete runs only.
- **Stopped runs:** runs that never saved metrics cannot appear in the tables, so they are listed at the
  bottom of the status card.

