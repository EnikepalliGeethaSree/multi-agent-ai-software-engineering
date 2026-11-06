# mini_shop

A tiny online-shop backend.

## Conventions

- **Money is always an integer number of cents.** Never store or compute prices as floats.
- Tax rates are whole percentages (`18` means 18%), passed to `money.apply_tax`.
- `users.get_user` returns `None` when the user does not exist; every caller must handle that.
- Functions that talk to the database raise `StorageError`, never return error codes.
