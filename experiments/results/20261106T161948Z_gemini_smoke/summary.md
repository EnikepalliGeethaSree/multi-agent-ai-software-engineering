# Gemini smoke test

Model: `gemini-3.6-flash`. Synthetic code only.

| Check | Kind | Result | Detail |
|---|---|---|---|
| missing_key | local | PASS | GEMINI_API_KEY is not set. Create a free key at https://aistudio.google.com/apikey and put it in .env (never in a config file). |
| key | local | PASS | variable: GEMINI_API_KEY |
| model_access | live | PASS | gemini-3.6-flash is listed (47 text models available) |
| json_and_schema | live | PASS | reply='ok' tokens=20+5 |
| agent_review | live | PASS | failed units=0 calls=1 findings=1 from LLM=1 rejected={} |
| invalid_key | live | PASS | attempts=1 kind=fatal status=400 key in message=False |
| failed_request_is_safe | live | PASS | failed units=1; static findings kept=0 |
| timeout_and_retry | live | PASS | attempts=2 kinds=['transient', 'transient'] |
| rate_limit_429 | simulated | not run live | not provoked live; unit tests with a fake client verify that it waits as the server asks, then retries |
| daily_quota | simulated | not run live | not provoked live; unit tests with a fake client verify that it stops at once and reports the Pacific reset time |
