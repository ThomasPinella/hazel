"""Tests for hazel.secrets.store."""

from __future__ import annotations

import os
import stat
import sys
from pathlib import Path

import pytest

from hazel import secrets as _secrets


@pytest.fixture
def secrets_dir(monkeypatch, tmp_path: Path) -> Path:
    """Redirect the secrets dir to a throwaway tmp_path for each test."""
    d = tmp_path / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    monkeypatch.setattr("hazel.config.paths.get_secrets_dir", lambda: d)
    return d


def test_set_then_get_roundtrips_value(secrets_dir: Path) -> None:
    _secrets.set("openweather", "abc123")
    assert _secrets.get("openweather") == "abc123"


def test_get_missing_raises(secrets_dir: Path) -> None:
    with pytest.raises(_secrets.SecretMissingError):
        _secrets.get("never_set")


def test_get_or_none_returns_none_when_missing(secrets_dir: Path) -> None:
    assert _secrets.get_or_none("never_set") is None
    _secrets.set("foo", "bar")
    assert _secrets.get_or_none("foo") == "bar"


def test_exists(secrets_dir: Path) -> None:
    assert not _secrets.exists("x")
    _secrets.set("x", "1")
    assert _secrets.exists("x")
    # Invalid names return False instead of raising
    assert not _secrets.exists("BAD NAME")


def test_delete(secrets_dir: Path) -> None:
    assert not _secrets.delete("nope")
    _secrets.set("gone", "value")
    assert _secrets.delete("gone") is True
    assert not _secrets.exists("gone")


def test_list_names_skips_dotfiles_and_invalid(secrets_dir: Path) -> None:
    _secrets.set("a", "1")
    _secrets.set("b", "2")
    # Simulate leftover temp files and invalid entries
    (secrets_dir / ".tmp.lock").write_text("tmp")
    (secrets_dir / "BAD NAME").write_text("bad")
    names = _secrets.list_names()
    assert names == ["a", "b"]


def test_list_names_empty_when_dir_missing(monkeypatch, tmp_path: Path) -> None:
    # Point to a dir that may not yet have anything in it
    d = tmp_path / "fresh-secrets"
    d.mkdir()
    monkeypatch.setattr("hazel.config.paths.get_secrets_dir", lambda: d)
    assert _secrets.list_names() == []


def test_name_validation(secrets_dir: Path) -> None:
    for bad in ["", "UPPER", "has space", "has/slash", "a" * 65, "emoji🔑"]:
        with pytest.raises(ValueError):
            _secrets.set(bad, "x")


def test_value_must_be_string(secrets_dir: Path) -> None:
    with pytest.raises(ValueError):
        _secrets.set("x", 42)  # type: ignore[arg-type]


def test_set_preserves_newlines_and_pem_like_payloads(secrets_dir: Path) -> None:
    pem = (
        "-----BEGIN PRIVATE KEY-----\n"
        "ABCDEF\n"
        "GHIJKL\n"
        "-----END PRIVATE KEY-----\n"
    )
    _secrets.set("tls_key", pem)
    assert _secrets.get("tls_key") == pem


def test_overwrite_replaces_value(secrets_dir: Path) -> None:
    _secrets.set("api", "first")
    _secrets.set("api", "second")
    assert _secrets.get("api") == "second"


def test_path_for_returns_expected_path(secrets_dir: Path) -> None:
    assert _secrets.path_for("foo") == secrets_dir / "foo"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_stored_file_has_0600_perms(secrets_dir: Path) -> None:
    _secrets.set("perm_check", "hi")
    mode = stat.S_IMODE(os.stat(secrets_dir / "perm_check").st_mode)
    assert mode == 0o600


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX permissions only")
def test_secrets_dir_has_0700_perms(tmp_path: Path, monkeypatch) -> None:
    # Re-derive the real get_secrets_dir against a fake home
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    from hazel.config import paths
    d = paths.get_secrets_dir()
    mode = stat.S_IMODE(os.stat(d).st_mode)
    assert mode == 0o700
