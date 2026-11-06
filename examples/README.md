# Sample input: `order_service.py`

A deliberately flawed file for trying the Code Review Agent. Review it with the dashboard (upload the
file) or the CLI:

```powershell
python -m marl_agents.cli review examples\order_service.py --out data\reports\order_service
python -m marl_agents.cli review examples\order_service.py --mode static_only   # no LLM
```

## Answer key (what a good review should find)

| # | Line | Function | Issue | Category | Who can catch it |
|---|---:|---|---|---|---|
| 1 | 15 | module | Hard-coded payment API key (CWE-798) | security | static (secret scan) |
| 2 | 22 | `get_customer` | SQL injection via string concatenation (CWE-89) | security | static (S608) + LLM |
| 3 | 28 | `load_settings` | `yaml.load` with the unsafe full Loader: arbitrary object construction (CWE-502) | security | static (S506) |
| 4 | 33 | `order_total` | Off-by-one: `range(1, ...)` skips the first item, so totals are wrong | bug | **LLM only** |
| 5 | 39 | `average_rating` | ZeroDivisionError when there are no reviews | edge_case | **LLM only** |
| 6 | 42 | `apply_coupon` | Mutable default `used_coupons=[]` is shared across calls, so coupons stay "used" forever | bug | static (B006) + LLM |
| 7 | 49 | `apply_coupon` | `TENOFF` can make the total negative | edge_case | **LLM only** |
| 8 | 54 | `notify_customer` | `customer.get("email").lower()` crashes when the email is missing | bug | **LLM only** |
| 9 | 55 | `notify_customer` | HTTP request without a timeout (CWE-400) | security | static (S113) |
| 10 | 63 | `export_invoice` | Command injection: user input in a `shell=True` command (CWE-78) | security | static (S602) + LLM |
| 11 | 67 | `save_order` | Global counter mutated: not thread-safe, resets on restart | maintainability | static (PLW0603) + LLM |
| 12 | 69 | `save_order` | File opened without `with`: the handle leaks | bug | static (AST check) |
| 13 | 78 | `cancel_order` | Bare `except: pass` hides database errors | error_handling | static (E722 / S110) |
| 14 | 83 | `shipping_cost` | Unused variable `unused_rate` | quality | static (F841) |
| 15 | 84 | `shipping_cost` | `== None` instead of `is None` | standards | static (E711) |
| 16 | 82 | `shipping_cost` | Public function without a docstring | documentation | static (AST check) |

**Clean code (should get no bug/security findings):** `format_price` (line 105) and `connect` (line 113).

The LLM-only rows (4, 5, 7, 8) are what static analysis cannot see; compare
`--mode static_only` with the default full mode to see the LLM's contribution.
