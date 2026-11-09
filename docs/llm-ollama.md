# LLM integration: Ollama (local development)

Ollama runs an open model on this machine. It needs no API key, has no quota, and no code leaves the
machine. It is for development and debugging of the agents. **Gemini stays the official evaluation
provider** (D27, D32); Ollama results are recorded and reported apart from Gemini results.

```
agent -> LLMProvider.generate_structured() -> OllamaProvider.generate()
                 |                                 |  context-window check (refuse before sending)
         schema validation, one retry              |  POST /api/chat  {format: json, options: {num_ctx,
         per-call log (Usage)                      |                   temperature, seed, num_predict}}
                                                   v
                                      Ollama server (http://localhost:11434) -> qwen2.5-coder:7b
```

`src/marl_agents/llm/ollama.py` uses the standard library (urllib); there is no new dependency.

## Setup

1. Install Ollama from <https://ollama.com> and start it (it listens on `http://localhost:11434`).
2. Pull the model once: `ollama pull qwen2.5-coder:7b` (about 4.7 GB, Q4_K_M).
3. Check it (local requests only, no Gemini quota is used):

   ```bash
   python -m marl_agents.cli models --provider ollama --config configs/ollama.yaml
   python -m marl_agents.cli check  --provider ollama --config configs/ollama.yaml
   ```

## Using it

Any command that takes `--provider` can run on Ollama:

```bash
python -m marl_agents.cli review examples/order_service.py --provider ollama --config configs/ollama.yaml
python -m marl_agents.cli bugs   examples/order_service.py --provider ollama --config configs/ollama.yaml
python -m marl_agents.cli eval ablation --benchmark planted --provider ollama --config configs/ollama.yaml
```

Or set `LLM_PROVIDER=ollama` (and optionally `OLLAMA_MODEL`, `OLLAMA_BASE_URL`) in the environment.
In the dashboard, pick **Provider: Ollama (local)** on the New review page; the server's default
provider is unchanged for other reviews.

Switching back to Gemini is dropping `--provider ollama` (or choosing Gemini in the dashboard). A
Gemini model id is never sent to Ollama and the reverse: `config.model_for` replaces a foreign id
with that provider's default.

## Configuration (`configs/ollama.yaml`)

| Setting | Value | Why |
|---|---|---|
| `model` | `qwen2.5-coder:7b` | must match `ollama list`; `OLLAMA_MODEL` overrides it |
| `context_window` | 16384 | sent as `num_ctx`; Ollama's default is smaller and cuts long prompts silently |
| `max_tokens` | 4096 | at 2048 a code review reply was cut off in a live run |
| `timeout_s` | 900 | CPU inference: one request can take minutes |
| `temperature`, `seed` | 0, 42 | reproducibility, as for Gemini |
| `review.concurrency` | 1 | one local model answers one request at a time |
| rate limits | none | no quota |

## Failures

Each failure is reported as what it is, and the review continues as a partial review where it can:

| Situation | Message (abridged) |
|---|---|
| Server not running | `Cannot reach Ollama at http://localhost:11434. Start it ...` |
| Model not pulled | `Ollama model 'qwen2.5-coder:7b' is not installed. Run: ollama pull qwen2.5-coder:7b` |
| Request too slow | `... timed out ... raise llm.timeout_s` |
| Prompt larger than the window | refused before sending; the agent retries without retrieved context |
| Reply cut off at `max_tokens` | not retried (the same request would be cut again) |
| Malformed JSON | repaired once with the validation error, then the unit fails |

## Measured speed (this machine, CPU)

From live runs on 2026-11-08 (Ollama 0.40.15, `qwen2.5-coder:7b` Q4_K_M):

- generation about 8.8 tokens per second; model load about 11 s;
- Bug Detection on `examples/order_service.py`: 8 LLM calls, 488 s, 8 findings;
- Code Review on the same file: 9 LLM calls (1 review unit + fix suggestions), 714 s, 14 findings
  (11 raw LLM findings, 10 valid, 1 rejected because its evidence was not in the file).

About 80 s per call, so a planted-issue ablation takes tens of minutes.

## Results stay separate

Every run records `llm_provider` and `llm_model`. `eval summary` excludes local-model runs, and every
run in the same ablation group, from the official (Gemini) tables, and shows them in a separate
"Local model" section with a "Local: Ollama (...)" badge (D36). A 7B local model and Gemini are
different systems; their numbers are not combined or compared as if they were one configuration.
