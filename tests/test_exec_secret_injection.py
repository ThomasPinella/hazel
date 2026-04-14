"""Tests that stored secrets are injected into ExecTool subprocess env."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from hazel import secrets as _secrets
from hazel.agent.tools.shell import ExecTool


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


@pytest.mark.skipif(sys.platform == "win32", reason="shell echo syntax differs on Windows")
@pytest.mark.asyncio
async def test_exec_injects_secret_env_vars(secrets_dir, tmp_path: Path) -> None:
    _secrets.set("openweather", "wx_key_value")
    _secrets.set("slack_bot", "slk_value")
    tool = ExecTool(working_dir=str(tmp_path))
    result = await tool.execute(
        command='echo "$HAZEL_SECRET_OPENWEATHER" && echo "$HAZEL_SECRET_SLACK_BOT"',
    )
    assert "wx_key_value" in result
    assert "slk_value" in result


@pytest.mark.skipif(sys.platform == "win32", reason="shell syntax differs on Windows")
@pytest.mark.asyncio
async def test_exec_unset_secrets_not_injected(secrets_dir, tmp_path: Path) -> None:
    # No secrets stored at all
    tool = ExecTool(working_dir=str(tmp_path))
    result = await tool.execute(
        command='echo "[$HAZEL_SECRET_NONEXISTENT]"',
    )
    assert "[]" in result


@pytest.mark.skipif(sys.platform == "win32", reason="shell syntax differs on Windows")
@pytest.mark.asyncio
async def test_exec_skips_secret_with_null_bytes(secrets_dir, tmp_path: Path) -> None:
    """A secret containing null bytes would crash subprocess via ValueError.
    The injection loop must skip it rather than taking down the whole exec."""
    _secrets.set("binary_blob", "before\x00after")
    _secrets.set("clean", "ok_value")
    tool = ExecTool(working_dir=str(tmp_path))
    # Command runs successfully — the null-byte secret was skipped, not propagated.
    result = await tool.execute(
        command='echo "clean=$HAZEL_SECRET_CLEAN blob=$HAZEL_SECRET_BINARY_BLOB"',
    )
    assert "clean=ok_value" in result
    # The binary blob was skipped — the env var should not have been set
    assert "before" not in result
    assert "after" not in result


@pytest.mark.skipif(sys.platform == "win32", reason="shell syntax differs on Windows")
@pytest.mark.asyncio
async def test_exec_hyphenated_secret_name_becomes_underscore_env_var(
    secrets_dir, tmp_path: Path,
) -> None:
    """Secret names with `-` are legal in the store, but shells can't
    dereference `$FOO-BAR`. The injection converts `-` to `_` so shell
    scripts can read the value."""
    _secrets.set("github-token", "ghp_hyphen_value")
    tool = ExecTool(working_dir=str(tmp_path))
    result = await tool.execute(
        command='echo "got=$HAZEL_SECRET_GITHUB_TOKEN"',
    )
    assert "got=ghp_hyphen_value" in result


@pytest.mark.skipif(sys.platform == "win32", reason="shell syntax differs on Windows")
@pytest.mark.asyncio
async def test_exec_updates_secrets_between_calls(secrets_dir, tmp_path: Path) -> None:
    tool = ExecTool(working_dir=str(tmp_path))

    _secrets.set("brave", "key_one")
    r1 = await tool.execute(command='echo "$HAZEL_SECRET_BRAVE"')
    assert "key_one" in r1

    # Updating the store should be reflected in the NEXT subprocess (env is
    # read at execute() time, not construction time).
    _secrets.set("brave", "key_two")
    r2 = await tool.execute(command='echo "$HAZEL_SECRET_BRAVE"')
    assert "key_two" in r2
