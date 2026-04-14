"""Unified secrets system for Hazel.

One mechanism for every sensitive value Hazel ever needs — API keys, OAuth
tokens, browser-redirect results, MCP auth headers, skill credentials. The
LLM never sees the raw value.

Public API re-exported from :mod:`hazel.secrets.store`.
"""

from hazel.secrets.store import (
    SecretMissingError,
    delete,
    exists,
    get,
    get_or_none,
    list_names,
    path_for,
    set,
    validate_name,
)

__all__ = [
    "SecretMissingError",
    "delete",
    "exists",
    "get",
    "get_or_none",
    "list_names",
    "path_for",
    "set",
    "validate_name",
]
