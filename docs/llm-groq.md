# Groq: the official evaluation provider (D38, D39)

The official LLM is **Groq**, model **`openai/gpt-oss-120b`**, pinned for the whole evaluation and
reached through Groq's OpenAI-compatible endpoint `https://api.groq.com/openai/v1`. The project uses
**one Groq organization, one API key, Developer tier (pay-as-you-go)** (D39). Gemini results (D27,
D37) stay as recorded, in their own sections and an appendix labelled partial. Ollama stays the local
development model (D32). Results of different providers or models never share a table (D36).

## Setup

The team enables the Developer tier and creates the key in the Groq console. Put it in `.env`
(git-ignored), never in a YAML file, code, docs, tests or logs. `.env.example` lists every variable
with placeholders:

```
GROQ_API_KEY=your_single_groq_api_key
GROQ_MODEL=openai/gpt-oss-120b
GROQ_RPM=TBD                               # from the console's limits page
GROQ_TPM=TBD
GROQ_DAILY_REQUEST_LIMIT=TBD               # optional
GROQ_DAILY_TOKEN_LIMIT=TBD                 # optional
GROQ_MAX_TOTAL_TOKENS=TBD                  # hard cap, cumulative
GROQ_MAX_ESTIMATED_COST_USD=TBD            # hard cap, cumulative
GROQ_INPUT_PRICE_PER_1M_TOKENS_USD=TBD     # from the console's pricing
GROQ_OUTPUT_PRICE_PER_1M_TOKENS_USD=TBD
GROQ_MAX_RETRIES=5
GROQ_BASE_BACKOFF_SECONDS=2
```

`TBD` or an empty value means "not set". No rate limit, quota or price is assumed by the code: each
comes from the console. Without a token or spending cap the provider refuses to start
(`llm.allow_uncapped: true` overrides this on purpose). A spending cap needs both prices.

```bash
python -m marl_agents.cli check --config configs/groq.yaml    # one tiny call + usage so far
python -m marl_agents.cli review path/to/repo --config configs/groq.yaml
python -m marl_agents.cli eval ablation ... --config configs/groq.yaml
```

`GROQ_*` variables override `configs/groq.yaml`; the values used are copied into the settings, so
every run's `config.yaml` records them. The old `GROQ_API_KEY_1` ... `GROQ_API_KEY_10` variables are
not read: there is no fallback to the retired ten-key setup.

## How a request is served

Code: `llm/groq.py` (provider), `llm/budget.py` (caps and cost), `llm/rate_limit.py` (pacing,
daily ledger), `llm/response_cache.py` (cache).

1. **Response cache.** Key = sha256 of provider, model, temperature, output limit, seed, stop
   sequences, JSON mode, provider options, the full prompt (every message) and the prompt-template
   version (the agents send theirs, e.g. `CodeReviewAgent:review=1.1,system=1.0`). A hit sends
   nothing, uses no tokens and costs nothing. Cut-off replies are not cached. `--no-cache` turns the
   cache off. Files are in `data/cache/llm_responses/groq/` and contain no key.
2. **Hard caps.** `UsageBudget` keeps cumulative input and output tokens in
   `data/cache/llm_quota/groq_<model>_budget.json`. Before each request it takes a worst case: the
   prompt at 3 characters per token (more tokens than the usual 4) plus the full `max_tokens`. If
   that could pass `GROQ_MAX_TOTAL_TOKENS` or `GROQ_MAX_ESTIMATED_COST_USD`, the request is not sent.
   The caps therefore hold across runs and restarts, and are never exceeded. To start a new budget,
   archive that ledger file on purpose.
3. **Daily caps (optional).** Requests and tokens per UTC day, in `..._daily.json`.
4. **Pacing.** A sliding 60-second window keeps requests and tokens per minute under `GROQ_RPM` and
   `GROQ_TPM` (the organization's limits). Unset limits are not paced locally.
5. **Server headers.** `x-ratelimit-limit-tokens` replaces the tokens-per-minute limit and
   `x-ratelimit-limit-requests` the daily request limit. No requests left blocks calls until
   `x-ratelimit-reset-requests`; too few tokens left pauses pacing until `x-ratelimit-reset-tokens`.

## Cost accounting

Estimated cost = input tokens x input price + output tokens x output price (USD per million, from
the console), kept separately for input and output. Reasoning tokens are reported by Groq as
completion tokens and are counted as output. This is an estimate, not the bill: Groq's usage page is
authoritative. `cli check` prints the cumulative tokens, the estimated cost and the caps, and every
evaluation shows its estimate before it starts (approval gate). An earlier rough estimate is never
reused: each one is recalculated from the configured prices.

## Failures and retries

| Server answer | What happens |
|---|---|
| 429, per-minute limit | Wait `retry-after` (else exponential backoff with jitter), retry. |
| 429, daily limit (wait over 120 s, or "per day", RPD, TPD) | `QuotaExhaustedError` with the reset time. |
| Cap reached (tokens, cost, daily) | `QuotaExhaustedError` before sending. |
| 401 / 403 | Stop: the key is missing, revoked or invalid. |
| 413 or "request too large" | `RequestTooLargeError`; the agent retries once without retrieved context. |
| 400 `json_validate_failed` | Retried once without JSON mode; our parser extracts the JSON. |
| Other 4xx | Stop: repeating a bad request cannot help. |
| 5xx, timeout, network error | Exponential backoff with jitter, retry. |

At most `GROQ_MAX_RETRIES` (default 5) attempts per request. Backoff for attempt k is uniform in
[b/2, b] with b = min(`GROQ_BASE_BACKOFF_SECONDS` x 2^k, 60 s). Every `QuotaExhaustedError` is the
existing checkpoint path: agents and runners save their progress and stop with "repeat the same
command"; the next run resumes from the checkpoint and the cache.

## What is recorded

- Every call logs model, prompt and completion tokens, latency and cache hit/miss
  (logger `marl_agents.llm.groq`).
- `Usage.call_log()` keeps the same fields per call; reviews save it in `stats["llm_calls"]`. Cache hits
  are counted apart (`cache_hits`) and are not calls.
- `GroqProvider.usage_report()`: calls, tokens, cache hits and misses, hit rate, 429 count, pacing
  wait, and the budget (cumulative tokens, estimated input/output cost, caps, prices).

## Security

- One key, only in `.env` (git-ignored). The ten keys of the retired setup are treated as
  compromised: the team revokes them in the console; they appear nowhere in the repository.
- The key is sent only in the `Authorization` header. Server text is scrubbed of `gsk_...` keys,
  bearer tokens and organization ids before it reaches an error or log; `repr()` never shows it.
- Tests use a fake HTTP layer (`httpx.MockTransport`) and a fake key; no test calls Groq.

## Tests

`tests/unit/llm/test_groq_provider.py`: configuration from `GROQ_*` (TBD handling), missing key, no
fallback to numbered keys, deterministic request, request and token pacing, header limits, 429 with
and without `retry-after`, backoff with jitter and the five-attempt limit, daily 429, rejected key,
too-large and bad requests, JSON-mode fallback, hard token cap, spending cap (input and output
priced separately), ledger across restarts, the agent's checkpoint on a cap, daily cap, cache hit/miss
and key contents, per-call metadata, and that the key never leaks.
