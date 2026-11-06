"""User lookup."""

from __future__ import annotations


class StorageError(Exception):
    """Raised when the user store cannot be read."""


_USERS: dict[int, dict[str, str]] = {
    1: {"name": "Asha", "email": "asha@example.com"},
    2: {"name": "Ravi", "email": "ravi@example.com"},
}


def get_user(user_id: int) -> dict[str, str] | None:
    """Return the user record, or None when no user has this id."""
    return _USERS.get(user_id)
