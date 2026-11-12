# Archived results

Superseded or partial runs, kept unchanged (never deleted). Not used in any results table.

| Folder | Why archived |
|---|---|
| 20261111T094623Z_planted_static_only, 20261111T094633Z_planted_llm_only, 20261111T094657Z_planted_static_llm, 20261111T094712Z_planted_static_llm_rag | Partial Groq planted ablation (repeat 1 of 3, D incomplete), stopped on 2026-11-11 before approval of the full evaluation. Moved on 2026-11-11 with the team's approval when the full planted evaluation started. |
| 20261111T121027Z_runtime_full_r5 | Superseded runtime benchmark: the Groq provider's reply cache answered rounds 2-5 of the "cold" runs from disk, so only round 1 was truly cold. Fixed in commit 43c6c70; the valid run is 20261111T121516Z_runtime_full_r5. Moved on 2026-11-12 with the team's approval. |
| logs/5c_bugs_loc_test_attempt1_crashed.log, logs/5d_bugs_det_test_attempt1_crashed.log | First BugsInPy test-split attempt, which crashed while unpacking ansible-7 (path longer than the Windows limit) before evaluating any bug, calling the LLM or writing a ledger row. Fixed in commit edd63d4. |
