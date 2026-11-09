# Common Python defect patterns

Known bug shapes the Bug Detection Agent looks for. Each section says how the defect shows, what
triggers it, and the usual fix. These are patterns to check against the code, not proof of a bug.

## Division by zero

`total / len(items)` or `a / b` where the divisor can be zero. Triggered by an empty collection or a
zero argument. Fix: check for the empty or zero case first and return a defined value or raise a clear
`ValueError`. Test with an empty list.

## Off-by-one and index out of range

`range(len(xs) + 1)`, `xs[len(xs)]`, `xs[i + 1]` at the last index, or slicing that drops one element.
Triggered by the last element or by an empty sequence. Fix: iterate the items directly, or compare with
`<` instead of `<=`. Test with sequences of length 0, 1 and 2.

## None dereference

Calling a method or attribute on a value that can be `None`: a dict `.get()` result, a regex
`match()`, a function that returns `None` on some paths, or a parameter defaulting to `None`. Triggered
by the missing key or the non-matching input. Fix: check for `None` before use, or make the producer
raise. Test the missing case.

## Missing return value

A function returns a value on some paths and falls off the end on others, so callers receive `None`.
Triggered by the branch without a `return`. Fix: return on every path, or raise for the impossible case.

## Mutable default argument

`def f(items=[])` or `def f(cache={})`: the default is created once and shared by every call, so state
leaks between calls. Fix: default to `None` and create the list inside the function.

## Swallowed exception

`except Exception: pass` or a bare `except:` that hides the real failure, leaving later code to work on
bad state. Fix: catch the specific exception, log it, and re-raise or return an explicit error.

## Resource leak

`open()`, a socket, a lock or a database connection that is not closed on every path, especially when
an exception is raised between opening and closing. Fix: use a `with` statement.

## Infinite loop

A `while` loop whose condition nothing in the loop changes, or `while True` without a reachable
`break`, `return` or `raise`. Triggered on the first iteration. Fix: update the loop variable, or add
the exit condition. Test with a timeout.

## Wrong comparison or condition

`if x is 1` (identity, not equality), `if a = b` typos caught as assignment in other languages,
`and`/`or` swapped, an inverted check, or `if items == []` style checks that miss other empty values.
Fix: compare values with `==`, test truthiness deliberately, and write the inverse case as a test.

## Mutation while iterating

Removing from or adding to a list or dict while looping over it skips items or raises `RuntimeError`.
Fix: iterate over a copy (`list(xs)`) or build a new collection.

## Integer and float surprises

`/` returning a float where an index is needed, `//` truncating negative numbers towards negative
infinity, or comparing floats with `==`. Fix: use the operator that matches the intent and
`math.isclose` for floats.

## Late-binding closure

Lambdas or inner functions created in a loop all see the last loop value. Fix: bind the value as a
default argument (`lambda x=x: ...`) or use `functools.partial`.
