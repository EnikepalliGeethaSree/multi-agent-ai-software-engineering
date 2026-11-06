# LLM integration: Google Gemini

Gemini through Google AI Studio's free tier is the default provider. Groq, OpenAI-compatible servers
and local models still work (`LLM_PROVIDER=groq`, and so on). `MockLLMProvider` stays the offline
provider for tests.

```
agent -> LLMProvider.generate_structured() -> GeminiProvider.generate()
                 |                                 |  daily budget check (DailyQuota)
         schema validation, one retry              |  input size check (max_input_tokens)
         per-call log (Usage)                      |  per-minute limiter (RateLimiter)
                                                   v
                                           google-genai SDK -> Gemini API
```

Nothing outside `src/marl_agents/llm/` imports the SDK, and the browser never talks to Google: the
key stays on the server and only the backend calls the API.

## Setup

1. Create a free key at <https://aistudio.google.com/apikey>. No payment method is needed.
2. Put this in `.env`:

   ```env
   LLM_PROVIDER=gemini
   GEMINI_API_KEY=your_key
   GEMINI_MODEL=gemini-3.8-flash
   ```

   `LLM_PROVIDER` and `GEMINI_MODEL` take priority over the older `MARL_LLM__*` lines, so existing
   lines do not need deleting. `GOOGLE_API_KEY` also works.
3. Verify it, spending one small request:

   ```bash
   python -m marl_agents.cli models    # models this key can use, with a recommendation
   python -m marl_agents.cli check     # key, model, JSON mode and parsing, end to end
   ```

`check` fails with a suggested replacement if the configured model is not available to the key. The
model is never swapped silently, because changing model mid-experiment would invalidate a comparison.

## Which model

Checked against Google's pricing and models pages on 2026-11-06:

| Model | Free tier | Status on Google's page |
|---|---|---|
| `gemini-3.8-flash` | Yes | Stable (generally available from 2 September 2026). The configured default |
| `gemini-3.6-flash` | Yes | Stable |
| `gemini-3.5-flash-lite` | Yes | Stable |
| `gemini-3.1-flash-lite` | Yes | Stable |

**Live result, 2026-11-06:** `gemini-3.8-flash` is listed for our key, but every generation request
failed with a high-demand error, so its use remains unverified. `gemini-3.6-flash` worked, including a
full agent review, and is the model to use: set `GEMINI_MODEL=gemini-3.6-flash` in `.env`.

## Free-tier limits

Switching provider does not remove quota problems. Google's rate-limit page states that limits are
per project, not per key; vary by model; are not guaranteed; and that daily quotas reset at midnight
Pacific time. It does not publish fixed free-tier numbers per model, so **read your own at
<https://aistudio.google.com/rate-limit>** and set them in `configs/gemini.yaml`.

**Measured on 2026-11-06:** Google's 429 for `gemini-3.6-flash` gave 20 generate requests per day, per
project, per model. That is very little: one review unit is one request, and a 4,000-line file needs
over 20 units. A cut-off reply also wastes a request, and reasoning counts against `llm.max_tokens`,
so that limit is now 16,384.

```yaml
llm:
  requests_per_minute: 10    # cautious starting point, not Google's figure
  tokens_per_minute: 200000  # cautious starting point, not Google's figure
  requests_per_day: 20       # stops before a request that is bound to fail
```

Several API keys in one project share a quota, and rotating accounts to get around limits is not
supported here and against the spirit of the free tier.

## What happens when something fails

| Situation | Behaviour |
|---|---|
| Per-minute limit (429) | Waits as long as the server says, then retries, within `llm.max_retries` |
| Daily or free-tier quota | Stops at once. The remaining units make no calls and the review ends **partial** |
| Prompt too large | Refused before sending if over `max_input_tokens`; the unit is retried once without retrieved context |
| Bad key, unknown model, bad request | Stops at once with the reason |
| Server error, timeout, network | Exponential backoff, within `llm.max_retries` |
| Malformed JSON | One retry with the validation error, then the unit fails |
| Reply cut off at `max_tokens` | Fails without a retry, since a retry would be cut off too. Raise `llm.max_tokens` |
| Blocked reply | Reported as a failure, never as "no findings" |

Retries are always bounded. API keys are scrubbed from every error message.

## Reusing work

Quota is the scarce resource, so before a call the agent:

- reuses the saved reply when the exact same request was already answered (`data/cache/llm_units/`,
  7 days);
- reviews identical code once and maps the findings onto its other copies, where they pass the same
  evidence validation;
- reuses deterministic static-analysis results for unchanged code (`data/cache/static_analysis/`);
- reuses identical RAG queries within a run.

Evaluation commands turn caching off, because a benchmark must measure real work. The file-size
benchmark measures it deliberately as its "warm" runs.

## Resuming after a quota stop

- **CLI:** run the same command again. Finished units come from the cache.
- **Dashboard:** open the review and press **Resume review**, or `POST /api/reviews/{id}/resume`.

The message says when the quota resets. A partial review keeps its uploaded input for
`review.resume_ttl_hours` (72) so it can resume. Deleting the review, or finishing it, removes that
input. Partial results always say so: in the CLI output, the dashboard and the performance record.

## Privacy: read this before reviewing private code

**On the free tier, Google may use what you send to improve its products.** Google's pricing page
marks "Used to improve our products" as **Yes** for the free tier and **No** for the paid tier. See
the [terms](https://ai.google.dev/gemini-api/terms). Your prompts contain your source code.

- Do not review confidential or proprietary code with the free tier.
- Use `--mode static_only`, which sends nothing anywhere, or a local model
  (`--provider local`), for private code.
- The CLI prints this warning on every LLM review, and the dashboard shows it on the New review page.

Findings that contain credentials are masked in reports as before. A unit with a detected secret is
never written to the on-disk reply cache. Other cached replies can quote your code, so they stay
under `data/`, which git ignores, and expire after `review.cache_ttl_hours`. `llm_only` mode does
not use the reply cache, because it has no secret scan.

## Not supported

- **Fine-tuning Gemini.** Google states that no model in the Gemini API or AI Studio supports
  fine-tuning, and it has no immediate plans to add it back. See [fine-tuning.md](fine-tuning.md).
- **Structured output by schema.** The provider uses JSON mode and validates replies with the
  project's Pydantic schemas, because the parser deliberately keeps good findings when one is
  malformed.
