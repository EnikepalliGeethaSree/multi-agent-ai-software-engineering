# Code Review Agent

Status: implemented and tested (static + LLM pipeline). Default LLM: Gemini free tier
([llm-gemini.md](llm-gemini.md)). Earlier real-LLM results were made on Groq (docs/results.md).

## Usage

```bash
# Review a directory, a .zip upload, or a single .py file -> JSON + Markdown + PDF report
python -m marl_agents.cli review path/to/repo --out data/reports/myrepo
python -m marl_agents.cli review upload.zip --mode static_only
python -m marl_agents.cli models                                             # models for GROQ_API_KEY
python -m marl_agents.cli check                                              # 1 tiny call: key + model OK?
python -m marl_agents.cli review path/to/repo                                # uses .env: gemini
python -m marl_agents.cli review repo --config configs/groq.yaml             # the older provider
python -m marl_agents.cli review app.py --provider openai --model <model>      # needs OPENAI_API_KEY
python -m marl_agents.cli review repo --provider local --model qwen2.5-coder   # Ollama / LM Studio
python -m marl_agents.cli review repo --no-rag                                # experiment config B
```

```python
from marl_agents.agents.code_review import CodeReviewAgent
from marl_agents.core.schemas import AgentRequest
from marl_agents.llm.factory import create_provider
from marl_agents.config import load_settings

s = load_settings()
agent = CodeReviewAgent(create_provider(s.llm), settings=s)
result = agent.run(AgentRequest(repo_path="path/to/repo"))  # whole repository
result = agent.run(AgentRequest(snippet=code, snippet_filename="x.py"))  # a snippet
result = agent.run(
    AgentRequest(
        repo_path="repo",  # a PR / diff
        options={"changed_lines": {"app/db.py": [[40, 52]]}},
    )
)
```

LangGraph (later): `graph.add_node("code_review", make_code_review_node(agent))` - the node reads
`state["request"]` and writes `state["code_review_result"]`. The agent itself never imports LangGraph.

## Pipeline

```
input (dir | zip | snippet | diff scope)
 -> ingestion      safe ZIP extraction (zip-slip, symlinks, zip bombs, size limits), file filter, temp workspace
 -> parsing        ast: symbols, imports, calls, line ranges; RepoIndex: call graph, callers, tests-by-name
 -> static         Ruff (isolated config, subprocess, timeout) | Radon CC/MI | AST checks | secrets | test gaps
 -> units          files split at top-level definitions into <= 200-line review units (1 LLM call each)
 -> context (RAG)  structural (callees, callers, tests, README) + dense retrieval (ChromaDB) + guidelines
 -> LLM review     versioned prompts; JSON findings + triage (confirm / false positive) of static findings
 -> validation     file exists, lines exist, evidence literally present; unambiguous relocation; scope
 -> dedup          rule-equivalence classes, LLM-vs-tool overlap, text similarity; merges keep all info
 -> severity       documented rubric (docs/severity-rubric.md)
 -> confidence     calibration + agreement; threshold filter; ranking; IDs CR-001...
 -> redaction      secrets masked in evidence
 -> reports        JSON / Markdown / PDF + dashboard summary (counts, issue density)
```

Modes (`review.mode`): `full` (static + LLM), `static_only` (no LLM), `llm_only` (no static tools).
Together with `rag.enabled` and `rag.structural_context` these give the ablations for the research
questions.

## Design decisions

| # | Decision | Why |
|---|---|---|
| CR1 | **Static analysis first, LLM second, never LLM alone.** Static findings are shown to the LLM, which triages them instead of repeating them. | Tools are precise and free; the LLM adds semantic issues (edge cases, logic) and explanations. Triage gives a measurable LLM contribution. |
| CR2 | **Evidence-verified findings.** An LLM finding must quote code that literally exists at (or unambiguously near) the cited lines; otherwise it is rejected. | Hallucination control; the rejection rate is itself an evaluation metric. |
| CR3 | **Relocate only when unambiguous** (exactly one match near the citation or in the file). | Guessing between several matches would silently produce wrong locations. |
| CR4 | **Severity by rubric, not by the LLM.** | Reproducible and defensible; LLM severity labels are inconsistent. |
| CR5 | **Structural context before dense retrieval.** | Retrieval benchmark: lexical dense retrieval finds a function's callees in the top-10 only ~54% of the time; the AST call graph finds them exactly. |
| CR6 | **Offline lexical `hashing` embedder as default**, sentence-transformers optional. | Works without model downloads/GPU; neural embeddings are an ablation. |
| CR7 | **Review units aligned to top-level definitions**, trivial files skipped. | Coherent context per LLM call, bounded cost. |
| CR8 | **Ruff with `--isolated`.** | A repository cannot change our rule set or load its own config. |
| CR9 | **Secrets masked in all outputs.** | Reports must not re-publish credentials found in the repo. |
| CR10 | **Test-gap analyzer disabled for CodeReviewer runs.** | A single patched file has no test context; the rule would fire on every sample. |
| CR11 | **Lenient LLM output parsing, item by item.** | One malformed finding must not discard the whole response. |
| CR12 | **Temporary workspaces deleted after each run.** | Uploaded code is untrusted and should not persist. |

## Metrics produced

| Level | Metric | Where |
|---|---|---|
| Pipeline (every run) | findings per stage, LLM rejection rate by reason, repairs, dedup merges, static triage verdicts, context items by source, tokens, timings | `ReviewResult.stats` |
| Planted benchmark | recall (all / static-detectable / LLM-only), defect precision, negative-control false positives, mean line error | `eval planted` |
| CodeReviewer cls | accuracy, precision, recall, F1 per severity threshold, ROC-AUC, bootstrap 95% CI, majority + always-positive baselines | `eval codereviewer --task cls` |
| CodeReviewer msg | smoothed BLEU-4, ROUGE-L, chrF (3 comment variants), coverage, bootstrap CI | `eval codereviewer --task msg` |
| RAG retrieval | Recall@K, Hit@K, MRR, nDCG@10 vs a random baseline | `eval retrieval` |
| Dashboard | issue density D = severity-weighted findings per KLOC (the 0-100 quality index was removed) | `reports.summarize` |

## Known limitations

- CodeReviewer samples are a single file + one hunk, with no repository, so RAG can only add guidelines
  there. The planted benchmark and real repositories are where repository context matters.
- CodeReviewer "needs a comment" labels reflect reviewer attention, not only defects (many comments are
  style/naming/design discussion), so a defect-oriented static baseline is expected to have low recall.
- The test-gap analyzer matches identifiers; indirect coverage is not detected.
- LLM-mode numbers must come from runs with a real provider; mock runs only verify the pipeline.

## Tests

`pytest` runs 155 offline tests (unit + integration, 92% line coverage), including: unsafe ZIPs, a
repository full of code that would write a marker file if executed (must never happen), prompt-injection
text, hallucinated / mis-cited LLM findings, diff-scoped review, determinism under concurrency, and the
planted benchmark as a regression gate (static recall must stay 100%, precision 100%).
