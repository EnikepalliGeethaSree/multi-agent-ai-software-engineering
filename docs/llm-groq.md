# Groq: the official evaluation provider (D38)

Since D38 the official LLM is **Groq**, model `openai/gpt-oss-120b`, through Groq's OpenAI-compatible
endpoint `https://api.groq.com/openai/v1`. Gemini results (D27, D37) stay as recorded, in their own
sections and an appendix. Ollama stays the local development model (D32). Results of different
providers or models are never put in one table (D36).

## Setup

Put up to ten keys in `.env` (never in a YAML file, never in code):

```
GROQ_API_KEY_1=...
GROQ_API_KEY_2=...
...
GROQ_API_KEY_10=...
GROQ_MODEL=openai/gpt-oss-120b     # optional; this is the default
```

Absent or empty variables are skipped and duplicate keys are used once, so one key is enough. Then:

```bash
python -m marl_agents.cli check --config configs/groq.yaml    # one tiny call + per-key status
python -m marl_agents.cli review path/to/repo --config configs/groq.yaml
python -m marl_agents.cli eval ablation ... --provider groq --config configs/groq.yaml
```

A single legacy `GROQ_API_KEY` without numbered keys still uses the older single-key provider
(`openai_compat.py`) unless `llm.key_rotation: true` (set in `configs/groq.yaml`).

## How a request is served

Code: `llm/groq.py` (provider), `llm/keys.py` (key manager), `llm/response_cache.py` (cache).

1. **Response cache.** The key is the sha256 of provider, model, temperature, output limit, seed,
   stop sequences, JSON mode, provider options, the full prompt (every message) and the prompt
   template version (the agents send theirs, e.g. `CodeReviewAgent:review=1.1,system=1.0`). A hit
   sends nothing and uses no quota. Cut-off replies are not cached. `--no-cache` turns the cache off.
   Files are under `data/cache/llm_responses/groq/` and hold no key or key label.
2. **Key selection.** The key manager gives the next *eligible* key after the one used last, in
   round-robin order, wrapping around after the last key. Selection is thread-safe (a lock).
   A key is not eligible while it cools down after a per-minute limit, after today's budget is spent,
   or after the server rejected it (401/403). A retry is a new request, so it moves on to the next
   eligible key; a failing key never stalls the rotation.
3. **Pacing.** Before sending, the manager waits until the request fits both the key's limits and the
   shared limits: requests and tokens per minute (sliding 60-second windows) and per day (ledgers in
   `data/cache/llm_quota/groq_<model>_<key>.json` and `..._shared.json`, UTC days, kept across
   restarts). The token estimate is replaced by the real usage once the reply arrives.
4. **Server headers.** `x-ratelimit-limit-*` replace the configured limits for that key. Groq's
   `*-requests` headers describe requests per day and `*-tokens` tokens per minute: no requests left
   marks the key spent until `x-ratelimit-reset-requests`; too few tokens left rests it until
   `x-ratelimit-reset-tokens`.

## Failures and retries

| Server answer | What happens |
|---|---|
| 429, per-minute limit | Rest the key for `retry-after` (else exponential backoff with jitter) and retry on the next eligible key. At most 5 attempts. |
| 429, daily limit (wait over 120 s, or "per day", RPD, TPD) | Mark the key spent until the server's reset, try the next key. |
| No eligible key left today | `QuotaExhaustedError` with the reset time. Agents and runners save their checkpoint and stop with "resume after ... with the same command". |
| 401 / 403 | The key is rejected: skipped for the rest of the process, the others carry on. All rejected: error. |
| 413 or "request too large" | `RequestTooLargeError`; the agent retries once without retrieved context. |
| 400 `json_validate_failed` | Retried once without JSON mode; our parser extracts the JSON. |
| Other 4xx | Stop: repeating a bad request cannot help. |
| 5xx, timeout, network error | Exponential backoff with jitter, retry (at most 5 attempts). |

## Limits: ten keys are not ten times the quota

Groq counts its limits **per organization**, not per key. Keys created in one organization share one
budget. So by default:

- `keys_share_limits: true`: a 429 or daily limit seen on one key rests or stops every key, instead of
  spending a request on each key to rediscover the same organization limit;
- the shared limits (`shared_requests_per_minute`, `shared_tokens_per_minute`,
  `shared_requests_per_day`, `shared_tokens_per_day`) default to one key's limits.

Per-key defaults are the free-plan limits of `openai/gpt-oss-120b` from Groq's rate-limits page
(2026-11): 30 requests/min, 1,000 requests/day, 8,000 tokens/min, 200,000 tokens/day. The limits page
in your Groq console is authoritative; every value is configurable in `configs/groq.yaml`. Use keys
in line with Groq's terms of service.

What the token limits mean in practice: a review request is several thousand prompt tokens plus about
1.5k output tokens (reasoning included), so 8K tokens/min allows roughly one review call per minute
and 200K tokens/day roughly 25-35 calls per day for the organization. Print the estimate before a run.

## What is recorded

- Every call logs model, key label (`key3`), prompt and completion tokens, latency and cache hit/miss
  (`logging`, logger `marl_agents.llm.groq`).
- `Usage.call_log()` keeps the same fields per call; reviews save it in `stats["llm_calls"]`, and
  `Usage.by_key()` aggregates requests, failures and tokens per key label. Cache hits are counted
  separately (`cache_hits`) and are not calls.
- `KeyManager.status()` reports per-key state and today's counts. `cli check` prints it.
- No API key ever reaches a log, an exception, a ledger, a checkpoint or a result file; error text from
  the server is scrubbed of keys, bearer tokens and organization ids. Tests check this.

## Tests

`tests/unit/llm/test_groq_rotation.py` uses a fake HTTP layer (`httpx.MockTransport`) and a fake
clock: round-robin and wrap-around, thread-safe selection, per-key and shared pacing, 429 handling,
key fallback, daily-limit stop with reset time, rejected keys, headers, cache hit/miss and cache key,
per-call metadata, ledgers across restarts, and that no secret leaks. No test calls a real API.
