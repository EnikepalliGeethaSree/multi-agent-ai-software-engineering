# Shop

A tiny shop backend used as a **planted-issue fixture** for the Code Review Agent.

## Modules
- `shop/db.py` - database access. All queries must use parameterised SQL.
- `shop/auth.py` - authentication; passwords must be hashed with bcrypt.
- `shop/pricing.py` - pricing rules.
- `shop/utils.py` - generic helpers.

## Conventions
- Never swallow exceptions; log and re-raise.
- Every network call must set a timeout.
