# Decision log

Short records of architectural/methodological decisions. Newest at the bottom. Status: accepted / open / superseded.

## D1 — No LLM training from scratch (accepted)
Pretrained LLM + prompting + RAG + static analysis + agent logic. Fine-tuning only as a separate experiment.

## D2 — LLM provider abstraction; model not yet chosen (accepted)
All calls via `LLMProvider`. Candidates: GPT, Gemini, Llama, Qwen, local models. `MockLLMProvider` for tests.
Model choice will be made by a small comparison on dev splits.

## D3 — ChromaDB for the first vector store (accepted)
FAISS remains an option behind the same retriever interface.

## D4 — Build the Code Review Agent first, LangGraph-independent (accepted)
Agents are plain Python classes; LangGraph wraps them as nodes once ≥2 agents exist.

## D5 — Agents recommend, don't modify (accepted)
Fixes and tests are suggestions. Automatic patch / PR generation is future work.

## D6 — ZIP upload is the primary input; GitHub API later (accepted)

## D7 — Static analysis + RAG + LLM, with validation of every finding (accepted)

## D8 — Three-configuration system experiment A/B/C (accepted)
A single LLM, B multi-agent without RAG, C multi-agent + RAG; identical samples, model, prompts.

## D9 — SWE-bench Lite resolve rate as primary system metric (open)
The approved deck lists SWE-bench Lite resolve rate as the primary system-level metric. Resolve rate needs
the system to *generate a patch* that makes FAIL_TO_PASS tests pass, which conflicts with D5 for the product
path. Proposed resolution: add a patch-generation step used only inside the evaluation harness (sandboxed),
or use a localization-based metric (did the system flag the file/function the gold patch changes?) as an
additional, cheaper system metric. **Needs a team decision.**

## D10 — Security Agent evaluated on Devign (C) while product targets Python (open)
See `datasets.md`. Needs a team decision on whether to add a Python security benchmark.

## D11 - Code Review Agent design (accepted)
Static analysis + evidence-verified LLM findings + rubric-based severity + structural (call-graph)
context ahead of dense retrieval. Twelve sub-decisions (CR1-CR12) with rationale are in
`docs/code-review-agent.md`.

## D12 - Offline-first defaults (accepted)
Default embedder is the dependency-free `hashing` lexical embedder and the default LLM provider is
`mock`, so the whole pipeline and test suite run without downloads, GPUs or API keys. Neural
embeddings (sentence-transformers) and real LLMs are opt-in and are compared as ablations.

## D13 - First benchmark numbers are a static-only baseline (accepted)
No LLM key was available when the agent was first evaluated, so the reported CodeReviewer numbers are
for `review.mode=static_only`. They are the baseline that LLM modes (and the A/B/C experiment) must beat.

## D14 - Groq as the LLM provider; default model openai/gpt-oss-120b (accepted)
Groq via its OpenAI-compatible API (`llm.provider: groq`, key `GROQ_API_KEY` in `.env`). The agent
throttles itself to Groq's per-minute quotas (client-side rate limiter, `retry-after` on HTTP 429)
and falls back from JSON mode when a model rejects it. The model was chosen by benchmarking the chat
models available to the key on 2026-09-29 (see `docs/results.md` section 5). Groq retires models;
`python -m marl_agents.cli models` lists what is available now.

## D15 - Dashboard: FastAPI + React/TypeScript/Tailwind, one process (accepted)
The API runs reviews as background jobs persisted under `data/jobs/` and serves the built frontend, so
`cli serve` is the only thing to start. Charts follow the dataviz method: severity uses a validated
ordinal ramp (the status palette failed the validator as a chart palette and is used only on badges
with icon + label). Details in `docs/dashboard.md`.

## D16 - Review a change, not only a repository (accepted)
Following the CodeReviewer paper (and the industrial SLR on code-review automation), the agent can
review a *change*: git base..head, uncommitted or staged work, or two ZIPs. Only changed lines are
reviewed, but the unchanged code that depends on them is analysed too (impact analysis: call-site
binding against the new signature, removed functions, an LLM behaviour check with the old and new
versions). Git is read with `ls-tree` + `cat-file --batch` (raw blobs: no checkout, no hooks, no
filters). Details: `docs/change-review.md`.

## D17 - Hunk risk: calibrated on validation, evaluated once on test (accepted, revised)
v1 used hand-set additive points. On CodeReviewer `cls` test (did a human comment on this hunk?) it
ranked **worse than chance** (AUC 0.434, while size alone scored 0.624). Static findings, the
heaviest v1 signal, do not predict human comments on this benchmark.

v2 is a 4-weight logistic model calibrated on the **validation** split. Its inputs are fixed in
advance; signals whose weight came out zero or negative are dropped, because a signal must never
lower risk. It reads as "estimated chance a reviewer comments". A guardrail keeps critical and high
findings from being ranked low. The test split was evaluated once with the shipped code. This is
statistical calibration of a few named weights, not training a model (principle 1); the
coefficients are documented in `docs/change-review.md`.

## D18 - Suggested fixes are verified, never applied (accepted)
A fix is shown only if the patched file parses and re-analysis finds no new issue. It is labelled
**verified** only when a tool confirms the original issue is gone (or Ruff marks its own fix safe);
LLM-only fixes are "suggested, review before applying". Fixes are never written to the analysed
repository. Vague LLM findings (two or more actionability problems) are dropped; one problem
downgrades the finding to info.

## D19 - Usefulness is judged by an LLM and checked against humans (accepted)
BLEU against one reference comment punishes a different-but-valid comment, so comments are also
rated for relevance and informativeness (1-5, CodeReviewer's human-evaluation criteria) by a blind,
reference-free LLM judge from a *different model family* than the reviewer. A blinded human rating
kit measures judge-human agreement (quadratic weighted kappa); the judge's numbers are cited only
alongside that agreement.

## D20 - Local git access only from this machine (accepted)
The dashboard can read a git repository from disk only when the request comes from loopback, names a
loopback Host (blocks DNS rebinding) and carries the `X-Marl-Client` header (forces a CORS preflight,
so other websites cannot trigger it). It can be disabled (`create_app(allow_local_git=False)`);
two-ZIP upload works everywhere.

## D21 - Living with free-tier LLM quotas (accepted)
Groq's free tier limits each model per minute (8k tokens), per day (e.g. 200k tokens for
gpt-oss-120b) and per request. On 2026-10-05 the daily limit was exhausted mid-benchmark, which
exposed three problems, now fixed:
- **Follow the server's counters.** Every response's `x-ratelimit-remaining-tokens` and `-reset`
  headers pause the client when the quota is low. These counters are account-wide, so they also
  cover the dashboard, CLI and evaluations sharing one key.
- **Fail fast on long waits.** A 429 asking to wait more than 2 minutes (daily quota) raises a clear
  error immediately ("daily quota reached for model X: try again in about N min, or choose another
  model") instead of retrying for minutes. The organisation id is removed from the message.
- **Request too large.** Raised without retries. The agent then reviews that unit once more
  without the retrieved project context (the code itself is never dropped) and records that it
  did. The dashboard and reports show a "partial review" warning whenever any LLM unit failed.

## D22 - Evaluation samples the LLM did not review are failures (accepted)
If any LLM review unit of a benchmark sample fails (quota, size, unparseable reply), the sample is
excluded and counted under `failure_reasons.llm`. Scoring it on static findings alone would
silently mix configurations. The 2026-10-05 gpt-oss-120b run predates this rule and was aborted
(`ABORTED.txt` in its folder).

## D23 - Five-component evaluation framework with time analysis (accepted)
The Code Review Agent is evaluated on five components only. Each has one purpose:
1. detection: precision, recall, F1;
2. CodeReviewer: precision and AUC (cls); coverage and chrF (msg);
3. RAG: Recall@10;
4. risk ranking: precision@top 10%, plus the existing AUC;
5. efficiency.

`eval summary` builds every table from saved runs. A missing configuration appears as "not run",
together with its command.

**Timing.** `core/timing.py` holds an in-memory `RunTimer`: `perf_counter` spans, each with start,
end and duration. It covers every review: static analysis per tool, RAG index and queries, LLM API
latency (measured in the provider after the rate limiter), validation, and report generation.
Other/orchestration is total minus components and is never forced to zero. `eval timing` adds the
fair-comparison rules: fixed inputs, interleaved repeats, concurrency 1, a fresh vector store per
run, a warm-up, conditions recorded, and incomplete runs excluded. RAG overhead is computed on
median active time.

Risk v1 is kept as a frozen evaluation baseline (`evaluation/runners/risk_v1.py`), and random is
reported as its exact expectation (the base rate).

## D24 - Quality index removed (accepted)
The 0-100 "quality index" (`100 * exp(-D/50)`) was removed from the dashboard, the reports and the
CLI. It was a heuristic with no ground truth to validate it, and it is not part of the evaluation
framework (D23). The underlying issue density D and the finding counts remain. Reviews saved
before the removal keep the old field in their files; it is ignored when loaded.

## D25 - Ablation configurations A-D and paired baseline comparison (accepted)
The contribution of each component is measured by switching it off. The four configurations are:
**A** Static Only, **B** LLM Only (no static, no RAG), **C** Static + LLM (no RAG) and
**D** Static + LLM + RAG (the shipped agent). They are defined once, in `evaluation/configurations.py`.
`apply_configuration` changes only `review.mode` and `rag.enabled`.
- **Classification.** A run is classified from its effective settings (`meta.experiment`, else
  `config.yaml`), never from its folder name. `--mode llm_only` with RAG on is its own label
  ("LLM + RAG"), not B. A static-only run's RAG flag is recorded as off, because no retriever is
  built in that mode; the agent's `stats` now say so.
- **Metadata.** Every run made through `eval planted|codereviewer|ablation` saves an `experiment`
  block in `meta.json` and `metrics.json`:
  - configuration flags, model, provider, temperature and seed;
  - RAG settings;
  - confidence threshold, evaluation rules and prompt versions;
  - sample count and an order-independent sample fingerprint;
  - failures, group id and repeat number.
- **Runs are never overwritten.** A second run in the same second gets an `_x2` suffix.
- **`eval ablation`** runs A-D on identical inputs with interleaved repeats. The comparison
  (`evaluation/comparison/`) scores CodeReviewer rows on the samples *every* configuration
  evaluated. Metrics are recomputed from the saved predictions with the runner's own functions;
  on the existing runs this reproduces the stored metrics exactly.
- **Never shown as results:** mock-LLM runs and incomplete planted runs.
- **Missing configurations** are N/A, together with the command that produces them. The tables
  also state observations, for example "size only has a higher ROC-AUC than risk model v2", even
  when a baseline wins.

## D26 - N/A instead of conventional 0 / 1 for undefined values (accepted)
- **Undefined ratios.** In the comparison tables, precision with TP + FP = 0, recall with
  TP + FN = 0, and F1 when either is undefined are **N/A**. The per-run `detection_metrics` keeps
  its historical precision of 1.0 for "no defect findings", for compatibility with saved runs.
  The comparison recomputes the ratio from TP and FP and does not inherit that 1.0.
- **Active time** (total − LLM quota waiting) is N/A for runs with more than one LLM worker. The
  limiter sums waits over workers, which produced a negative active time (−282 s) for the
  2026-10-12 planted run at concurrency 2. Planted ablation runs therefore use concurrency 1.
  Findings do not depend on concurrency; this is tested.
- **Planted ROC-AUC** is N/A by design: the suite has positives only.
- **Metric scales** were verified. BLEU-4, ROUGE-L and chrF are ×100 (0-100) by design; coverage
  is 0-1.

## D27 - Google Gemini free tier as the default provider (accepted)
Requested by the project guide, because Groq's daily quota stopped evaluation runs. Paid services
are out of scope. Gemini is reached through the official `google-genai` SDK inside `llm/gemini.py`;
`LLMProvider` is unchanged for callers, and Groq stays available as a legacy option.
- **Model.** `gemini-3.8-flash`: Stable (generally available from 2 September 2026), and listed as
  free on Google's pricing page on 2026-11-06. Live API availability and free-tier eligibility for
  our configured API key remain unverified. `cli check` verifies it against the key and suggests a
  replacement.
  The model is never replaced automatically: a silent change would invalidate a comparison.
- **Precedence.** `LLM_PROVIDER` and `GEMINI_MODEL` beat `MARL_LLM__*` and YAML. A leftover model id
  from another provider is not sent to Gemini.
- **Quota.** A quota stop raises `QuotaExhaustedError`, and the remaining units make no calls. Unit
  replies are cached by exact request, so a rerun repeats only unfinished work. Identical code is
  reviewed once. Daily counts are local and advisory; the server's 429 always wins.
- **Limits are not assumed.** Google publishes no fixed free-tier numbers per model, so the shipped
  per-minute values are cautious starting points and the daily limits default to unset.
- **Privacy.** Free-tier content may be used to improve Google's products. Reviews print a warning,
  and the dashboard shows it. See `docs/llm-gemini.md`.
- **Comparability.** All earlier LLM results were made on Groq with other models. They are not
  merged with Gemini results; `eval before-after` keeps the two apart and compares only runs on the
  same samples.

## D28 - Classifier fine-tuning, and what the data allowed (accepted)
Principle 1 (we do not train the LLM) stands for the main model. The project guide asked for
fine-tuning, and Gemini offers none, so this is the separately scoped experiment the principle
allows: a small code model fine-tuned to predict which changes draw a review comment.
- **Label leak in the raw data.** In the CodeReviewer `cls` train chunks all 132,918 positives have
  only `id, msg, oldf, patch, y`, and all 132,918 negatives also have `lang, proj, idx`. Filtering on
  `lang == "py"` therefore selects negatives only: the "39,630 Python examples" in the earlier
  feasibility note are all label 0. Metadata is never shown to the model. Python is recognised from
  content, by one rule for both classes. Tagged negatives measure that rule: it kept 0 of 91,369
  non-Python records and 69.2% of Python ones.
- **Split independence.** valid and test share 28 projects and 664 identical Python patches, so
  tuning on valid would reach into test. Projects are divided (seed 42) into a tuning half and a
  testing half, duplicates are removed across splits, and the repository-disjoint test set is the
  primary result. Train positives have no project name, so project overlap with them cannot be ruled
  out; exact and near-duplicate patches are removed instead.
- **Safety.** The classifier orders or gates LLM work. It cannot remove a finding, and it can never
  gate a unit holding a critical, high or high-confidence static finding. It applies only to change
  reviews, because it learned from diffs.
- **Placement.** Inference is in `llm/classifier.py`, the one package allowed to import
  `transformers`. Training is in `training/`, which the review path never imports. A run with the
  classifier is configuration E and can never be counted as D.
- **Training data.** Train positives are far larger than real ones and negatives lean on a few
  projects, so a TF-IDF model scored 0.82 on held-out train and 0.62 on dev. Python records are capped
  per project and size-matched to dev, then mixed with non-Python `valid` records, whose classes were
  collected the same way. Test projects are excluded. Of 16,000 examples, 8,701 are not Python.
- **Threshold.** It maximises dev balanced accuracy, because best-F1 chose 0.05 and flagged almost
  everything. It is stored with the model, and gating uses it unless `classifier.threshold` is set,
  so the operating point in use is the one that was tested.
- **Result.** ROC-AUC 0.723 on the repository-disjoint test, above TF-IDF (0.645), change size (0.635)
  and static analysis (0.541). This run does not show better comments or lower LLM use.
- **Generative fine-tuning is not done.** See `docs/fine-tuning.md`.

## D29 - Execution-time analysis (accepted)
Every review stores a `PerformanceRecord`, and `benchmark_runtime` measures small, medium and large
files. A value that was not measured stays null and is shown as "Unavailable", never as 0. Finer
stages break the six D23 components down without changing them, so older runs stay comparable. Time
measured in a run that later fails is kept. Failed, partial and skipped runs never enter timing
statistics, and their counts are always shown.

## D30 - Live Gemini validation and free-tier scope (accepted)
- **Model.** `gemini-3.8-flash` stayed the configured default, but it failed live with a high-demand
  error, so runs used `gemini-3.6-flash` by explicit choice. The model is never replaced automatically.
- **Quota.** The free tier gave 20 requests per day, per project, per model. Benchmarks are scoped to fit
  and spread over days with `--resume`, never around the limit with extra keys or accounts.
- **Output limit.** Reasoning counts against `llm.max_tokens`, and 4096 cut replies off, so it is 16,384.
- **Classifier comparison.** It runs on dev samples only, through `eval classifier-ablation`, because the
  test split has been used once. Dev tuned the classifier, so this is not an independent test.
- **ChromaDB.** Version 1.5.9 can fail when one process reads several saved collections in turn. The store
  reopens a persistent client once and retries, and a failure that persists is still raised.

## D31 - Bug Detection Agent and its BugsInPy evaluation (accepted)
- **Built on the Code Review Agent.** `BugDetectionAgent` subclasses it through small hooks (prompts,
  analyzers, unit selection, claim checks), so quota handling, resume, validation, reports and the
  dashboard job flow are shared. Code Review's behaviour did not change. `FlowAnalyzer` is left out of
  `default_analyzers()` so saved Code Review baselines stay comparable.
- **Two tracks, not a repository scan.** BugsInPy labels one bug per commit, so a finding matching no
  label is not proven false, and a scan cannot measure precision. Detection shows each changed
  function buggy and fixed in separate requests, and the fixed one is the negative. Localization ranks
  functions from the failing test. Both run without executing project code.
- **Fixed-function findings count as false positives under both scorings.** Otherwise precision "at the
  fixed lines" would be 1.0 by construction.
- **A suspect containing a fixed line counts as a hit.** A live reply named the outer function of a
  closure and described the bug correctly, and strict matching scored that a miss.
- **Failing test as the input to localization.** It comes from the fixed commit, as is standard in
  fault localization. BugsInPy has no issue text, and a traceback would need execution.
- **Configurations.** Localization needs candidates in all of A-D, so the call-graph walk is common to
  all four, and "RAG" there means retrieval adds candidates. This differs from D25, where the call
  graph is part of RAG. Detection follows D25.
- **Own split.** BugsInPy has none. Dev and test share no project. The test split needs `--final`.
- **Quota.** At one request per bug and configuration (two in detection), 20 requests a day means runs
  span days. Finished samples are kept in a ledger keyed by model, prompts and harness version, and
  the same command continues.
- **D9 is still open,** but the localization harness is the cheap metric D9 proposed for SWE-bench Lite.
- **Not built:** repro confirmation in Docker, and Fig. 3 stages 7-8 (bug-report store, learning loop).

## D32 - Ollama for local development; Gemini stays the official provider (accepted)
- **Why.** Gemini's free tier allows 20 requests a day, which is too few to develop and debug two agents.
  Ollama runs `qwen2.5-coder:7b` on this machine: no key, no quota, and no code leaves the machine.
- **Native API, not the OpenAI-compatible one.** `/api/chat` accepts `options.num_ctx`. The compatible
  endpoint uses Ollama's small default window and cuts long prompts silently. `OllamaProvider` uses
  urllib only (no new dependency), sets a 16K window, and refuses before sending a prompt that would
  not fit (`RequestTooLargeError`, so the agent retries without context).
- **Failures named for what they are.** An unreachable server, a model that is not installed, a
  timeout, HTTP errors and malformed JSON each give their own message. A malformed reply is repaired
  once; a reply cut off at `max_tokens` is not retried (the same request would be cut again).
- **Reply budget 4096.** At 2048 a code review reply was cut off in a live run.
- **Separation of results.** Every run records provider and model. The evaluation summary keeps local
  runs, and every run of a local run's ablation group, out of the official tables and reports them
  in their own section (D36). Gemini remains the provider of record for benchmark results.
- **Switching.** `--provider ollama --config configs/ollama.yaml` on the CLI, or the Provider choice
  per review in the dashboard (`ReviewOptions.provider`, built by `config.with_provider`). A model id
  of the other provider is never sent (`config.model_for`).

## D33 - Evidence basis, snippets and cited context on every finding (accepted)
- **Evidence basis** (`static_confirmed`, `llm_with_context`, `llm_inferred`) says where a finding's
  support comes from, after deduplication: any static source makes it `static_confirmed`. It is a
  provenance label, never a probability.
- **Cited context is checked.** Context items are shown with ids (C1, C2, ...). The LLM may list ids in
  `context_refs`; the agent keeps only ids it really showed and records what each was. Invalid ids are
  dropped and counted (`stats.context_refs_invalid`), so a cited source is never invented.
- **Snippet** is read from the file at the finding's lines (at most 12), and masked for secret
  findings. It is never taken from the LLM.
- Both review prompts moved to version 1.1. Earlier runs record 1.0, so results stay attributable.

## D34 - Agent-specific guidance in shared RAG (accepted)
- One guidance collection (`guidelines_v2`, which adds `bug_patterns.md` and `review_examples.md`), filtered
  per agent by `GUIDELINE_FILES`. Code Review reads standards, error handling, security and review
  examples; Bug Detection reads bug patterns, error handling and security.
- A retrieval failure (e.g. a vector-store error) is logged, recorded in `stats.rag_errors` and the
  run's errors, and the unit is reviewed without that context.

## D35 - A crashing static analyzer makes a review partial, not failed (accepted)
- Before, one analyzer raising an exception aborted the whole review. Now it is logged, listed in
  `stats.analyzers_failed`, timed as a failed stage, and the review is marked `partial`, with an
  error saying its findings are missing. Evaluation runs can see this, so a lost tool is never silent.
- New design checks (`design`: duplicated functions, PEP 8 naming) join `default_analyzers()`. The
  static planted baseline was re-run after the change and is identical (22 findings, 16/17 matched,
  precision 1.0, no false positive in the clean file).
- The infinite-loop rule (`BUG-INFINITE-LOOP`, `loop`) is in `bug_analyzers()` only, like D31's flow rules.
- **Deduplication picks the closest duplicate.** A finding that duplicates several clusters joins the
  one with the same category, then equivalent rules, then most shared lines, then most similar
  wording. Before it joined the first, and an LLM "swallowed exception" merged into a resource-leak
  finding on the line above. Whether a finding merges, and the merge count, are unchanged.

## D36 - One ablation group per comparison table (accepted)
- The planted table took the latest run of each configuration separately, so a later stand-alone
  static run, or another model's ablation, could replace one row of a group. Rows are now aligned on
  the group of the newest LLM run. Local-model groups are reported in their own section.

## D37 - Gemini continuation runs use the prompt-1.0 code, commit a54c6c9 (accepted, 2026-11-09)
- The team chose to keep Gemini on prompt version 1.0, so every Gemini experiment matches the official
  planted results (section 12) and the classifier ablation checkpoint. More than the prompt file
  changed after a54c6c9: context rendering (D33), the guidance collection (D34) and the static
  analyzers (D35) all change what the model sees. Pinning only `review.md` would not reproduce the
  1.0 requests or reuse their cache.
- The Gemini runs therefore use a git worktree at **a54c6c9** (`git worktree add --detach
  ../marl-agents-gemini-p10 a54c6c9`). Its `data/`, `capstone-datasets/` and `experiments/results/`
  are directory junctions to the main project, so it shares the quota ledger, caches and checkpoints,
  and runs are saved with the others. A local launcher (`data/gemini_p10/run.py`, not tracked) puts the
  worktree's `src` first on the path and loads the main `.env` into the environment. Runs record
  commit `a54c6c9...` and prompts system 1.0, review 1.0 (bug: system, review and localize 1.0).
- Correction (audit, 2026-11-12): the planted Gemini results of results section 12 were not produced
  at a54c6c9. Their runs record commit `ff1b67c...-dirty`: an ancestor of a54c6c9 whose uncommitted
  changes were committed next (522805c, a54c6c9). The continuation runs use a54c6c9 as stated.
- Consequence: the Gemini numbers measure the a54c6c9 agents, without the D33-D35 additions. Ollama
  runs, the dashboard and the tests use the current code. The two sets of results are reported
  apart (D36) and never merged.
- Cleanup when the Gemini work ends: remove the three junctions first (`cmd /c rmdir <junction>`,
  which deletes only the link), then `git worktree remove`. Never run a git command in the worktree that
  rewrites files under `experiments/results/`: it would reach the main project's results through the
  junction.

## D38 - Groq becomes the official evaluation provider, with round-robin keys (accepted, 2026-11-10)
- The team moved the official LLM from Gemini (D27) to **Groq, `openai/gpt-oss-120b`**. Gemini's
  20 requests per day made the remaining experiments take weeks. Completed Gemini results stay as
  recorded; partial Gemini runs are reported in an appendix table labelled partial. Ollama stays the
  local development model (D32). Results are never mixed across providers or models (D36).
- `llm/groq.py` posts to Groq's OpenAI-compatible endpoint with `httpx` (testable with a fake HTTP
  layer). `llm/keys.py` is a central key manager: up to ten keys (`GROQ_API_KEY_1..10`), round-robin
  over eligible keys, thread-safe, per-key and shared limits per minute and per day, cool-down on 429,
  skip until reset on a daily limit, skip rejected keys, and `QuotaExhaustedError` with the reset time
  when no key is left (the existing checkpoint path). `llm/response_cache.py` caches replies on disk.
- **Groq limits are per organization.** Keys of one organization share a single budget, so shared
  limits default to one key's limits and `keys_share_limits: true` applies a limit seen on one key to
  all. More keys therefore add resilience and accounting, not quota. Details: docs/llm-groq.md.
- Groq runs use the current code and prompts (review 1.1), not the a54c6c9 worktree of D37.
- The older single-key Groq path (`openai_compat.py` with `GROQ_API_KEY`) is kept for compatibility.

## D39 - One Groq key on the Developer tier; the ten-key rotation is retired (accepted, 2026-11-10)
- Supersedes the key-rotation part of D38. The project uses one Groq organization, one API key
  (`GROQ_API_KEY`), the Developer tier (pay-as-you-go) and one pinned model, `openai/gpt-oss-120b`.
  Groq counts limits per organization, so several keys added no quota; one key is simpler and safer.
- Removed: the key manager (`llm/keys.py`), round-robin selection, per-key accounting and key labels.
  The old `GROQ_API_KEY_1..10` variables are not read. The ten old keys are treated as compromised and
  are revoked by the team; none appears in the repository.
- Kept: temperature 0 and seed, requests- and tokens-per-minute pacing, `x-ratelimit-*` headers, 429
  and `retry-after`, exponential backoff with jitter (5 attempts), the sha256 response cache and
  `--no-cache`, per-call token, latency and cache tracking, and the checkpoint stop.
- Added for pay-as-you-go: cumulative hard caps on tokens and estimated cost (`llm/budget.py`),
  enforced before each request with a worst-case estimate so they are never exceeded; input and output
  cost computed separately from console prices; the provider refuses to start without a cap.
- No limit, quota or price is hard-coded; all come from the Groq console through `.env`. The
  free-plan figures used in D38 are no longer applied.

## D40 - Risk v2 stays the default hunk ranker; the classifier comparison is saved-score only (accepted, 2026-11-10)
- The hunk-risk samples are the CodeReviewer cls test split, which holds the classifier's held-out test
  set. The team decided that set is not used again for scoring, training, threshold tuning or model
  selection. Part 3.8 therefore compares risk v2, change size and the classifier only from scores
  already saved (`eval ranker-saved-scores`, report in `experiments/evaluation_summary/`), on the
  1,771 repository-disjoint changes, labelled as a saved-score secondary analysis.
- The classifier ranks better there, but a default chosen on test results would be tuned on test.
  Risk v2 therefore stays the default. Changing it needs a comparison on data that is not the test set.

## D41 - The classifier gate is not re-evaluated on "unused train-split" changes (accepted, 2026-11-10)
- Part 3.9 asked for a gate evaluation on Python train-split changes the classifier never trained on and
  that development never used, verified by IDs, repositories and patch hashes, and said to stop if that
  cannot be established. It cannot (`scripts/check_unused_train_holdout.py`, report in
  `experiments/evaluation_summary/unused-train-holdout-check.json`):
  1. The recipe comparison's "balanced only" recipe kept the whole minority class: all 15,813 Python
     train negatives were used in development (31,626 = 2 x 15,813). No unused negative exists.
  2. The unused records are positives only, and none of the 26,208 has a project name, so their
     repository identity cannot be checked against the test projects.
  3. The only other negatives (11,969 Python-tagged records that failed the content filter) would tie
     the label to "parses as Python".
- So the experiment was not run, and neither test nor dev samples were substituted. The classifier gate
  result stays the existing dev-sample ablation, reported as tuning data, not an independent test.
