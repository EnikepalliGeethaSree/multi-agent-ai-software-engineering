# Security guidance for Python (OWASP Top 10 2021 / CWE)

## Injection (OWASP A03, CWE-89 SQL injection, CWE-78 OS command injection)
- Never build SQL with f-strings, `%` or `+` concatenation of user input; use parameterised queries
  (`cursor.execute("... WHERE id = %s", (user_id,))`) or an ORM.
- Never pass user input to `os.system`, `subprocess` with `shell=True`, or `eval`/`exec` (CWE-95).
  Use argument lists: `subprocess.run(["ls", path], check=True)`.
- Validate and normalise file paths from users to prevent path traversal (CWE-22):
  resolve the path and check it stays inside the allowed directory.

## Broken access control (OWASP A01, CWE-284, CWE-862 missing authorization)
- Every endpoint or function that reads/modifies another user's data must check that the caller is
  authorised (ownership or role check), not only authenticated.
- Deny by default; do not rely on hidden URLs or client-side checks.
- Beware of insecure direct object references (IDs taken straight from the request).

## Cryptographic failures (OWASP A02, CWE-327, CWE-916, CWE-330)
- Do not use MD5/SHA-1 for security; store passwords with bcrypt, scrypt or argon2 (with salt).
- Use the `secrets` module (not `random`) for tokens, passwords and nonces.
- Never disable TLS verification (`verify=False`) (CWE-295).

## Identification and authentication failures (OWASP A07, CWE-798, CWE-287)
- Never hard-code passwords, API keys or tokens in source code or config committed to git;
  load them from environment variables or a secrets manager, and rotate leaked secrets.
- Compare secrets with `hmac.compare_digest` to avoid timing attacks (CWE-208).

## Software and data integrity failures (OWASP A08, CWE-502 deserialization)
- Never `pickle.loads`/`marshal.loads` untrusted data; use `yaml.safe_load`, not `yaml.load`.
- Verify integrity of downloaded code or data.

## Security misconfiguration (OWASP A05, CWE-489, CWE-16)
- Never run Flask/Django with debug mode enabled in production.
- Do not bind services to 0.0.0.0 unless intended; set secure cookie flags.

## Security logging and monitoring failures (OWASP A09, CWE-778, CWE-532)
- Log security-relevant events (failed logins, access denials) but never log secrets, passwords
  or full personal data (CWE-532).
- Do not swallow exceptions silently (CWE-390).

## Server-side request forgery (OWASP A10, CWE-918)
- Validate/allow-list URLs before fetching user-supplied URLs from the server.

## Denial of service (CWE-400)
- Set timeouts on network calls; bound input sizes; avoid catastrophic-backtracking regexes on
  user input (CWE-1333).
