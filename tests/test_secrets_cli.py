"""Tests for the `hazel auth` and `hazel secret list` CLI commands."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hazel import secrets as _secrets
from hazel.cli.commands import app


@pytest.fixture
def secrets_dir(monkeypatch, tmp_path: Path) -> Path:
    d = tmp_path / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    monkeypatch.setattr("hazel.config.paths.get_secrets_dir", lambda: d)
    return d


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


def test_auth_from_env_saves_secret(runner, secrets_dir, monkeypatch) -> None:
    monkeypatch.setenv("MY_KEY", "envelope_value")
    result = runner.invoke(app, ["auth", "mykey", "--from-env", "MY_KEY"])
    assert result.exit_code == 0, result.output
    assert _secrets.get("mykey") == "envelope_value"
    assert "mykey" in result.output


def test_auth_from_env_missing_var_fails(runner, secrets_dir, monkeypatch) -> None:
    monkeypatch.delenv("NOPE", raising=False)
    result = runner.invoke(app, ["auth", "foo", "--from-env", "NOPE"])
    assert result.exit_code == 1
    assert "NOPE" in result.output
    assert not _secrets.exists("foo")


def test_auth_prompts_for_value(runner, secrets_dir, monkeypatch) -> None:
    # Stub getpass to avoid actual terminal interaction
    monkeypatch.setattr("hazel.cli.auth.getpass.getpass", lambda prompt="": "pasted_value")
    result = runner.invoke(app, ["auth", "brave_api"])
    assert result.exit_code == 0, result.output
    assert _secrets.get("brave_api") == "pasted_value"


def test_auth_empty_value_rejected(runner, secrets_dir, monkeypatch) -> None:
    monkeypatch.setattr("hazel.cli.auth.getpass.getpass", lambda prompt="": "")
    result = runner.invoke(app, ["auth", "empty"])
    assert result.exit_code == 1
    assert not _secrets.exists("empty")


def test_auth_remove(runner, secrets_dir) -> None:
    _secrets.set("togo", "bye")
    result = runner.invoke(app, ["auth", "togo", "--remove"])
    assert result.exit_code == 0, result.output
    assert not _secrets.exists("togo")


def test_auth_remove_noop_when_missing(runner, secrets_dir) -> None:
    result = runner.invoke(app, ["auth", "ghost", "--remove"])
    assert result.exit_code == 0  # soft-noop, not an error
    assert "nothing to remove" in result.output.lower() or "no secret" in result.output.lower()


def test_auth_show_prints_value(runner, secrets_dir) -> None:
    _secrets.set("showme", "SECRET_123")
    result = runner.invoke(app, ["auth", "showme", "--show"])
    assert result.exit_code == 0, result.output
    assert "SECRET_123" in result.output


def test_auth_show_missing_fails(runner, secrets_dir) -> None:
    result = runner.invoke(app, ["auth", "nope", "--show"])
    assert result.exit_code == 1


def test_auth_overwrite_requires_confirm(runner, secrets_dir, monkeypatch) -> None:
    _secrets.set("reuse", "old")
    monkeypatch.setattr("hazel.cli.auth.getpass.getpass", lambda prompt="": "new_value")
    # Decline: value should stay
    result = runner.invoke(app, ["auth", "reuse"], input="n\n")
    assert result.exit_code == 0, result.output
    assert _secrets.get("reuse") == "old"


def test_auth_overwrite_accepted_updates_value(runner, secrets_dir, monkeypatch) -> None:
    _secrets.set("reuse", "old")
    monkeypatch.setattr("hazel.cli.auth.getpass.getpass", lambda prompt="": "new_value")
    result = runner.invoke(app, ["auth", "reuse"], input="y\n")
    assert result.exit_code == 0, result.output
    assert _secrets.get("reuse") == "new_value"


def test_auth_force_skips_overwrite_prompt(runner, secrets_dir, monkeypatch) -> None:
    monkeypatch.setenv("X", "forced")
    _secrets.set("reuse", "old")
    result = runner.invoke(app, ["auth", "reuse", "--from-env", "X", "--force"])
    assert result.exit_code == 0, result.output
    assert _secrets.get("reuse") == "forced"


def test_invalid_name_rejected(runner, secrets_dir) -> None:
    result = runner.invoke(app, ["auth", "BAD NAME"])
    assert result.exit_code == 1
    assert "invalid" in result.output.lower()


def test_conflicting_flags_rejected(runner, secrets_dir) -> None:
    """--show, --remove, --from-env cannot be combined."""
    result = runner.invoke(app, ["auth", "foo", "--show", "--remove"])
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output.lower()

    result = runner.invoke(app, ["auth", "foo", "--show", "--from-env", "X"])
    assert result.exit_code == 1

    result = runner.invoke(app, ["auth", "foo", "--remove", "--from-env", "X"])
    assert result.exit_code == 1


def test_secret_list_empty(runner, secrets_dir) -> None:
    result = runner.invoke(app, ["secret", "list"])
    assert result.exit_code == 0, result.output
    assert "no secrets" in result.output.lower()


def test_secret_list_shows_names_not_values(runner, secrets_dir) -> None:
    _secrets.set("alpha", "value_that_should_not_be_leaked")
    _secrets.set("beta", "another_value")
    result = runner.invoke(app, ["secret", "list"])
    assert result.exit_code == 0, result.output
    assert "alpha" in result.output
    assert "beta" in result.output
    assert "value_that_should_not_be_leaked" not in result.output
    assert "another_value" not in result.output
