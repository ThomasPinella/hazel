"""File-backed secret store.

One file per secret under ``~/.hazel/secrets/<name>`` (chmod ``0600``), with
the directory itself restricted to ``0700``. All reads go through
:func:`get`/:func:`get_or_none`; writes go through :func:`set`, which uses
atomic rename to avoid torn files.

The LLM never sees raw values — only existence checks via the
``request_secret`` agent tool.
"""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

_NAME_RE = re.compile(r"^[a-z0-9_-]+$")
_MAX_NAME_LEN = 64


class SecretMissingError(KeyError):
    """Raised when a secret is requested but not present in the store."""


def validate_name(name: str) -> None:
    """Reject names containing anything outside ``[a-z0-9_-]`` or too long.

    Public so that CLI and agent tools can surface the same error message
    the store would raise on write, without calling into private helpers.
    """
    if not isinstance(name, str):
        raise ValueError(f"secret name must be a string, got {type(name).__name__}")
    if not name:
        raise ValueError("secret name must not be empty")
    if len(name) > _MAX_NAME_LEN:
        raise ValueError(f"secret name must be at most {_MAX_NAME_LEN} chars")
    if not _NAME_RE.fullmatch(name):
        raise ValueError(
            f"secret name {name!r} is invalid — must match [a-z0-9_-]+"
        )


def _secrets_dir() -> Path:
    """Return the secrets directory, creating it with ``0700`` perms if needed.

    Imported lazily so the CLI test suite can monkey-patch
    ``hazel.config.paths.get_secrets_dir``.
    """
    from hazel.config.paths import get_secrets_dir
    return get_secrets_dir()


def path_for(name: str) -> Path:
    """Return the absolute path of the secret file (may or may not exist)."""
    validate_name(name)
    return _secrets_dir() / name


def exists(name: str) -> bool:
    """Return True if a secret with this name is stored."""
    try:
        return path_for(name).is_file()
    except ValueError:
        return False


def get(name: str) -> str:
    """Return the secret value. Raises :class:`SecretMissingError` if absent."""
    p = path_for(name)
    if not p.is_file():
        raise SecretMissingError(name)
    return p.read_text(encoding="utf-8")


def get_or_none(name: str) -> str | None:
    """Return the secret value, or None if not set."""
    try:
        return get(name)
    except SecretMissingError:
        return None


def set(name: str, value: str) -> None:  # noqa: A001 — match public spec
    """Write a secret atomically with ``0600`` permissions.

    The directory is created with ``0700`` if it doesn't exist. We preserve
    the value exactly as provided — no stripping — so PEM payloads and
    trailing bytes round-trip cleanly.
    """
    validate_name(name)
    if not isinstance(value, str):
        raise ValueError(f"secret value must be a string, got {type(value).__name__}")

    d = _secrets_dir()
    target = d / name

    # Write to a temp file in the same dir, then atomic rename. This avoids
    # a half-written file if the process dies mid-write.
    fd, tmp_path_str = tempfile.mkstemp(prefix=f".{name}.", dir=str(d))
    tmp_path = Path(tmp_path_str)
    try:
        try:
            os.fchmod(fd, 0o600)
        except (AttributeError, OSError):
            # Windows / non-POSIX: best effort only
            pass
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(value)
        os.replace(tmp_path, target)
    except Exception:
        # Clean up the temp file on failure
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise

    # Re-chmod after rename in case the filesystem's umask clobbered it.
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


def delete(name: str) -> bool:
    """Remove a secret. Returns True if it existed, False if not."""
    p = path_for(name)
    if not p.is_file():
        return False
    p.unlink()
    return True


def list_names() -> list[str]:
    """Return a sorted list of stored secret names."""
    try:
        d = _secrets_dir()
    except Exception:
        return []
    if not d.is_dir():
        return []
    out = []
    for p in d.iterdir():
        # Skip dotfiles (temp files, hidden state)
        if p.name.startswith("."):
            continue
        if not p.is_file():
            continue
        try:
            validate_name(p.name)
        except ValueError:
            continue
        out.append(p.name)
    out.sort()
    return out
