# Code review examples

Short examples of useful review comments, for the Code Review Agent. Each names the problem, why it
matters, and a concrete change. They show the expected tone and level of detail.

## Duplicated logic

"`calculate_invoice_total` and `calculate_order_total` repeat the same discount loop. A future change
to discounts could be applied to one and missed in the other. Extract `apply_discounts(lines)` and call
it from both."

## Long function

"`process_order` is 120 lines and mixes validation, pricing and persistence. Split it into
`validate_order`, `price_order` and `save_order`; each can then be tested on its own."

## Deep nesting

"Four levels of `if` inside the loop make the happy path hard to see. Return early for the invalid cases
(guard clauses) so the main logic sits at one indentation level."

## Unclear naming

"`d`, `tmp2` and `doIt` do not say what they hold or do. Rename to `discount_rate`, `pending_orders` and
`submit_payment`; PEP 8 asks for lower_case_with_underscores for functions and variables."

## Too many parameters

"`create_user` takes nine arguments, several always passed together. Group the address fields into an
`Address` dataclass; call sites become shorter and harder to get wrong."

## Missing error handling

"`load_config` assumes the file exists and contains valid JSON. A missing file raises a raw
`FileNotFoundError` at startup. Catch it, report which path was expected, and exit with a clear message."

## Inefficient implementation

"Membership is checked with `if user_id in user_list` inside a loop over all orders, which is O(n*m).
Build `set(user_list)` once before the loop."

## Magic numbers

"`if retries > 3` and `sleep(0.25)` appear in three places. Name them `MAX_RETRIES` and
`RETRY_DELAY_S` at module level so they change in one place."

## Comment that restates the code

"`# increment i` above `i += 1` adds nothing. Comments should explain why: here, why the counter starts
at 1 rather than 0."
