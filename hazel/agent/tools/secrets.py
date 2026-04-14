"""Agent tool: ``request_secret`` — ask the user to set a credential.

The LLM never sees the raw value. It calls this tool with a ``name`` and a
human-readable ``purpose``; the tool reports whether the secret is already
stored (``ready``) or still missing (``missing`` plus the exact command the
user must run).

Pair this with ``queue_user_action`` when the authentication is something
the user should do later, not right now. Use ``request_secret`` when you
need to know the credential's availability *in this turn*.
"""

from __future__ import annotations

import json
from typing import Any

from hazel import secrets as _secrets
from hazel.agent.tools.base import Tool


class RequestSecretTool(Tool):
    """Check or request a stored secret by name."""

    @property
    def name(self) -> str:
        return "request_secret"

    @property
    def description(self) -> str:
        return (
            "Check whether Hazel has a stored credential (API key, OAuth token, "
            "password, webhook URL, etc.) under a given name — WITHOUT ever "
            "revealing the value to you. Use this whenever you hit anything "
            "sensitive during setup or runtime.\n\n"
            "Returns JSON: {\"status\": \"ready\"} if the secret is available, "
            "or {\"status\": \"missing\", \"command\": \"hazel auth <name>\"} "
            "if the user must set it first.\n\n"
            "DO NOT ask the user to paste credentials in chat. When status is "
            "'missing', tell the user the exact command in the 'command' field "
            "and move on — do not loop or retry. If the task can continue "
            "without the secret, proceed; otherwise queue a user action or "
            "stop and wait."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Secret name (lowercase, [a-z0-9_-], <=64 chars). "
                        "Examples: 'gmail', 'openweather', 'slack_bot', "
                        "'my_custom_mcp_bearer'."
                    ),
                },
                "purpose": {
                    "type": "string",
                    "description": (
                        "One short sentence explaining why you need this "
                        "credential (shown to the user alongside the command). "
                        "Example: 'so I can read your Gmail inbox'."
                    ),
                },
            },
            "required": ["name", "purpose"],
        }

    async def execute(self, name: str, purpose: str, **kwargs: Any) -> str:
        # Validate the name shape before touching the filesystem. A bad name
        # is a prompt bug — surface it clearly so the LLM can correct.
        try:
            _secrets.validate_name(name)
        except ValueError as e:
            return f"Error: {e}"

        if _secrets.exists(name):
            return json.dumps({"status": "ready", "name": name})

        return json.dumps({
            "status": "missing",
            "name": name,
            "command": f"hazel auth {name}",
            "message": (
                f"Tell the user to run: hazel auth {name} "
                f"(for: {purpose}). Do not paste credentials yourself."
            ),
        })
