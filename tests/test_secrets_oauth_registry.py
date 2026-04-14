"""Tests for the OAuth registry and `hazel auth` routing."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from typer.testing import CliRunner

from hazel import secrets as _secrets
from hazel.secrets import registry as _registry
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


def test_github_is_registered_by_default() -> None:
    assert _registry.has_oauth("github")


def test_unknown_name_is_not_registered() -> None:
    assert not _registry.has_oauth("nope_never_registered")


def test_register_and_run_custom_handler() -> None:
    try:
        _registry.register("fakeprov", lambda: "fake-token-xyz")
        assert _registry.has_oauth("fakeprov")
        assert _registry.run_oauth("fakeprov") == "fake-token-xyz"
    finally:
        _registry.unregister("fakeprov")


def test_run_oauth_on_unregistered_raises() -> None:
    with pytest.raises(KeyError):
        _registry.run_oauth("not_registered_anywhere")


def test_auth_routes_to_registered_oauth_handler(
    runner, secrets_dir, monkeypatch,
) -> None:
    """`hazel auth <name>` should invoke the registered OAuth handler,
    not prompt via getpass."""
    called = {"count": 0}

    def handler() -> str:
        called["count"] += 1
        return "oauth_token_from_handler"

    # Also force getpass to fail loudly if accidentally invoked, so a
    # regression that falls through to the plain-key path is caught.
    def blown_getpass(prompt=""):
        raise AssertionError("getpass should not be used when OAuth is registered")

    monkeypatch.setattr("hazel.cli.auth.getpass.getpass", blown_getpass)

    try:
        _registry.register("testprov", handler)
        result = runner.invoke(app, ["auth", "testprov"])
        assert result.exit_code == 0, result.output
        assert called["count"] == 1
        assert _secrets.get("testprov") == "oauth_token_from_handler"
    finally:
        _registry.unregister("testprov")


def test_auth_oauth_handler_failure_exits_nonzero(
    runner, secrets_dir, monkeypatch,
) -> None:
    def handler() -> str:
        raise RuntimeError("simulated OAuth failure")

    try:
        _registry.register("flaky", handler)
        result = runner.invoke(app, ["auth", "flaky"])
        assert result.exit_code == 1
        assert "simulated OAuth failure" in result.output
        assert not _secrets.exists("flaky")
    finally:
        _registry.unregister("flaky")


def test_github_handler_errors_without_client_id(monkeypatch) -> None:
    monkeypatch.delenv("HAZEL_GITHUB_CLIENT_ID", raising=False)
    with pytest.raises(RuntimeError) as excinfo:
        _registry.run_oauth("github")
    msg = str(excinfo.value)
    assert "HAZEL_GITHUB_CLIENT_ID" in msg
