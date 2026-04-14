"""Tests for the RequestSecretTool agent tool."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from hazel import secrets as _secrets
from hazel.agent.tools.secrets import RequestSecretTool


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


@pytest.mark.asyncio
async def test_ready_when_secret_exists(secrets_dir) -> None:
    _secrets.set("gmail", "token_value")
    tool = RequestSecretTool()
    raw = await tool.execute(name="gmail", purpose="send email")
    data = json.loads(raw)
    assert data["status"] == "ready"
    assert data["name"] == "gmail"
    # Value is never included in the response
    assert "token_value" not in raw


@pytest.mark.asyncio
async def test_missing_returns_command_to_run(secrets_dir) -> None:
    tool = RequestSecretTool()
    raw = await tool.execute(name="brave", purpose="run web searches")
    data = json.loads(raw)
    assert data["status"] == "missing"
    assert data["name"] == "brave"
    assert data["command"] == "hazel auth brave"
    assert "run web searches" in data["message"]


@pytest.mark.asyncio
async def test_invalid_name_returns_error(secrets_dir) -> None:
    tool = RequestSecretTool()
    raw = await tool.execute(name="BAD NAME", purpose="test")
    assert raw.startswith("Error:")


def test_tool_schema_exposes_required_params() -> None:
    tool = RequestSecretTool()
    schema = tool.to_schema()
    assert schema["function"]["name"] == "request_secret"
    params = schema["function"]["parameters"]
    assert set(params["required"]) == {"name", "purpose"}


def test_tool_registered_in_agent_loop(tmp_path: Path) -> None:
    """Sanity check: the loop registers RequestSecretTool by default, and the
    tool shows up under its declared name in the runtime registry."""
    from hazel.agent.loop import AgentLoop
    from hazel.bus.queue import MessageBus
    from hazel.providers.base import LLMProvider, LLMResponse

    class _FakeProvider(LLMProvider):
        def get_default_model(self) -> str:
            return "fake-model"

        async def chat(self, **kwargs):  # type: ignore[override]
            return LLMResponse(content="")

        def supports_tool_calls(self) -> bool:
            return True

    loop = AgentLoop(
        bus=MessageBus(),
        provider=_FakeProvider(),
        workspace=tmp_path / "ws",
    )
    assert "request_secret" in loop.tools.tool_names


def test_system_prompt_mentions_request_secret(tmp_path: Path) -> None:
    """The system prompt instructs the agent to use request_secret."""
    from hazel.agent.context import ContextBuilder
    workspace = tmp_path / "ws"
    workspace.mkdir()
    cb = ContextBuilder(workspace)
    prompt = cb.build_system_prompt()
    assert "request_secret" in prompt
    assert "hazel auth" in prompt
