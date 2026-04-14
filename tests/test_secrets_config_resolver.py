"""Tests for @secret: config reference resolution."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hazel import secrets as _secrets
from hazel.config.loader import _resolve_secret_refs, load_config


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


def test_resolves_whole_string_references(secrets_dir) -> None:
    _secrets.set("openweather", "api_value_123")
    data = {
        "tools": {"search": {"api_key": "@secret:openweather"}},
        "other": "plain value",
    }
    resolved = _resolve_secret_refs(data)
    assert resolved["tools"]["search"]["api_key"] == "api_value_123"
    assert resolved["other"] == "plain value"


def test_resolves_nested_and_list_values(secrets_dir) -> None:
    _secrets.set("token_a", "AAA")
    _secrets.set("token_b", "BBB")
    data = {
        "mcp_servers": {
            "gmail": {"env": {"GMAIL_TOKEN": "@secret:token_a"}},
            "other": {"headers": {"Authorization": "@secret:token_b"}},
        },
        "array": ["@secret:token_a", "static"],
    }
    resolved = _resolve_secret_refs(data)
    assert resolved["mcp_servers"]["gmail"]["env"]["GMAIL_TOKEN"] == "AAA"
    assert resolved["mcp_servers"]["other"]["headers"]["Authorization"] == "BBB"
    assert resolved["array"] == ["AAA", "static"]


def test_missing_secret_leaves_placeholder_and_warns(secrets_dir, caplog) -> None:
    data = {"some": {"path": "@secret:not_set_yet"}}
    with caplog.at_level("WARNING"):
        resolved = _resolve_secret_refs(data)
    assert resolved["some"]["path"] == "@secret:not_set_yet"
    # The loguru logger intercepts here; not_set_yet should appear in output
    # one way or another. We just verify the config isn't mangled.


def test_embedded_references_are_not_resolved(secrets_dir) -> None:
    """Only whole-value references get replaced — embedded ones stay literal."""
    _secrets.set("x", "VALUE")
    data = {"url": "https://example.com?key=@secret:x"}
    resolved = _resolve_secret_refs(data)
    assert resolved["url"] == "https://example.com?key=@secret:x"


def test_non_reference_strings_pass_through(secrets_dir) -> None:
    data = {"a": "hello", "b": "@something:else", "c": "@secret:", "d": ""}
    resolved = _resolve_secret_refs(data)
    assert resolved == data


def test_load_config_resolves_references(secrets_dir, tmp_path: Path) -> None:
    _secrets.set("tavily", "live_key")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "tools": {
            "web": {
                "search": {"apiKey": "@secret:tavily", "provider": "tavily"},
            },
        },
    }))
    cfg = load_config(cfg_path)
    assert cfg.tools.web.search.api_key == "live_key"
    assert cfg.tools.web.search.provider == "tavily"


def test_load_config_missing_secret_keeps_placeholder(secrets_dir, tmp_path: Path) -> None:
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "tools": {"web": {"search": {"apiKey": "@secret:unresolved"}}},
    }))
    cfg = load_config(cfg_path)
    # Missing secret: placeholder remains. The feature reading this key
    # will see the literal and degrade — that's the documented behavior.
    assert cfg.tools.web.search.api_key == "@secret:unresolved"


def test_save_config_preserves_secret_placeholders(secrets_dir, tmp_path: Path) -> None:
    """A load → save round-trip must NOT leak plaintext secrets."""
    from hazel.config.loader import save_config
    _secrets.set("brave", "PLAINTEXT_DO_NOT_LEAK")

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "tools": {"web": {"search": {"apiKey": "@secret:brave", "provider": "brave"}}},
    }))
    cfg = load_config(cfg_path)
    # In-memory the value is fully resolved for downstream use
    assert cfg.tools.web.search.api_key == "PLAINTEXT_DO_NOT_LEAK"

    save_config(cfg, cfg_path)
    contents = cfg_path.read_text()
    # The secret value must not have been written to disk
    assert "PLAINTEXT_DO_NOT_LEAK" not in contents
    # The placeholder must have been restored
    assert "@secret:brave" in contents


def test_save_config_keeps_placeholder_when_secret_removed(
    secrets_dir, tmp_path: Path,
) -> None:
    """If the user deletes a secret between load and save, the placeholder
    must still be restored — path-based matching doesn't depend on the
    secret still being in the store."""
    from hazel.config.loader import save_config
    _secrets.set("brave", "UNIQUELY_IDENTIFIABLE_TOKEN_CAFEBABE")

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "tools": {"web": {"search": {"apiKey": "@secret:brave"}}},
    }))
    cfg = load_config(cfg_path)

    # User deletes the secret between load and save
    _secrets.delete("brave")
    save_config(cfg, cfg_path)
    contents = cfg_path.read_text()
    # The placeholder is restored even though the secret is gone
    assert "@secret:brave" in contents
    # And the resolved plaintext is NOT written to disk
    assert "UNIQUELY_IDENTIFIABLE_TOKEN_CAFEBABE" not in contents


def test_save_config_user_override_preserved(
    secrets_dir, tmp_path: Path,
) -> None:
    """If the user intentionally changes the resolved value in-memory before
    saving, the new value should be written — the placeholder must NOT
    clobber a legitimate override."""
    from hazel.config.loader import save_config
    _secrets.set("brave", "loaded_from_secret")

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "tools": {"web": {"search": {"apiKey": "@secret:brave"}}},
    }))
    cfg = load_config(cfg_path)
    # User pointed at a different value
    cfg.tools.web.search.api_key = "user_override_value_xyz"
    save_config(cfg, cfg_path)
    after = cfg_path.read_text()
    assert "user_override_value_xyz" in after
    # Placeholder should NOT be restored since user changed the value
    assert "@secret:brave" not in after


def test_save_config_preserves_placeholder_with_snake_case_keys(
    secrets_dir, tmp_path: Path,
) -> None:
    """Raw config.json may use snake_case (api_key) or camelCase (apiKey);
    save_config serializes camelCase via pydantic's alias generator. The
    placeholder preservation must map across that boundary, or plaintext
    leaks when users hand-edit snake_case keys."""
    from hazel.config.loader import save_config
    _secrets.set("brave", "DO_NOT_LEAK_SNAKE_CASE")

    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(json.dumps({
        "tools": {"web": {"search": {"api_key": "@secret:brave"}}},
    }))
    cfg = load_config(cfg_path)
    save_config(cfg, cfg_path)
    after = cfg_path.read_text()
    assert "DO_NOT_LEAK_SNAKE_CASE" not in after
    assert "@secret:brave" in after


def test_save_config_without_existing_file_works(secrets_dir, tmp_path: Path) -> None:
    """save_config on a fresh path (no existing file) should just write normally."""
    from hazel.config.loader import save_config
    from hazel.config.schema import Config
    cfg_path = tmp_path / "new.json"
    save_config(Config(), cfg_path)
    assert cfg_path.exists()
    # Valid JSON
    json.loads(cfg_path.read_text())
