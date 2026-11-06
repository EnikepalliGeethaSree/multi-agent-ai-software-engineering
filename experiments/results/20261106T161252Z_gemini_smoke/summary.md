# Gemini smoke test

Model: `gemini-3.8-flash`. Synthetic code only.

| Check | Kind | Result | Detail |
|---|---|---|---|
| missing_key | local | PASS | GEMINI_API_KEY is not set. Create a free key at https://aistudio.google.com/apikey and put it in .env (never in a config file). |
| key | local | PASS | variable: GEMINI_API_KEY |
| model_access | live | PASS | gemini-3.8-flash is listed (47 text models available) |
| json_and_schema | live | FAIL | Gemini call failed after 6 attempt(s): This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later. |
| agent_review | live | FAIL | failed units=1 calls=0 findings=0 from LLM=0 rejected={} |
| invalid_key | live | PASS | attempts=1 kind=fatal status=400 key in message=False |
| failed_request_is_safe | live | PASS | failed units=1; static findings kept=0 |
| timeout_and_retry | live | PASS | attempts=2 kinds=['transient', 'transient'] |
| rate_limit_429 | simulated | not run live | not provoked live; unit tests with a fake client verify that it waits as the server asks, then retries |
| daily_quota | simulated | not run live | not provoked live; unit tests with a fake client verify that it stops at once and reports the Pacific reset time |
