"""Registry of known OAuth providers for the unified secret store.

Each entry in :data:`_OAUTH_PROVIDERS` is a callable that runs an interactive
OAuth flow and returns the resulting token string. The caller — usually
``hazel auth <name>`` — then writes the token to the secrets store.

Adding a provider:

1. Write a zero-argument function that performs the OAuth dance (browser
   launch, device flow, PKCE, whatever the service requires) and returns
   the final access token as a string.
2. Register it in :data:`_OAUTH_PROVIDERS` under the secret name that
   ``request_secret`` / ``@secret:`` users will reference.

The shell tool then picks up ``HAZEL_SECRET_<NAME>`` automatically.
"""

from __future__ import annotations

import json
import os
import time
from typing import Callable
from urllib import request as _urlrequest
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

_TokenProvider = Callable[[], str]


def _github_device_flow() -> str:
    """GitHub OAuth device flow — returns an access token.

    Uses GitHub's documented device-flow endpoints (no client secret
    required). The client_id must be provided via ``HAZEL_GITHUB_CLIENT_ID``
    — register a personal OAuth app at
    https://github.com/settings/applications/new and set that env var.

    We keep this in the secret registry (not providers/) because the token
    is a generic GitHub credential that MCP servers, skills, and shell
    scripts all consume the same way.
    """
    client_id = os.environ.get("HAZEL_GITHUB_CLIENT_ID")
    if not client_id:
        raise RuntimeError(
            "GitHub OAuth requires HAZEL_GITHUB_CLIENT_ID. Register an OAuth "
            "app at https://github.com/settings/applications/new with device "
            "flow enabled, then set the env var and retry. Alternatively, "
            "run `hazel auth github --from-env GITHUB_TOKEN` to paste a "
            "pre-existing personal access token."
        )

    scope = os.environ.get("HAZEL_GITHUB_SCOPES", "repo read:user")

    # 1) Ask GitHub for a device + user code
    resp = _post_form(
        "https://github.com/login/device/code",
        {"client_id": client_id, "scope": scope},
    )
    if "error" in resp or "device_code" not in resp:
        raise RuntimeError(f"GitHub device-code request failed: {resp}")
    device_code = resp["device_code"]
    user_code = resp.get("user_code", "")
    verification_uri = resp.get("verification_uri", "https://github.com/login/device")
    interval = int(resp.get("interval", 5))
    expires_in = int(resp.get("expires_in", 900))

    print(f"\nGo to: {verification_uri}")
    print(f"Enter code: {user_code}\n")
    try:
        import webbrowser
        webbrowser.open(verification_uri)
    except Exception:
        pass

    # 2) Poll for the token
    deadline = time.monotonic() + expires_in
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            token_resp = _post_form(
                "https://github.com/login/oauth/access_token",
                {
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
        except (HTTPError, URLError) as e:
            raise RuntimeError(f"GitHub token poll failed: {e}") from e

        if "access_token" in token_resp:
            return token_resp["access_token"]

        err = token_resp.get("error")
        if err in ("authorization_pending", None):
            continue
        if err == "slow_down":
            interval += 5
            continue
        if err in ("expired_token", "access_denied", "unsupported_grant_type"):
            raise RuntimeError(f"GitHub OAuth failed: {err}")
        # Unknown error — bail rather than spin
        raise RuntimeError(f"GitHub OAuth returned: {token_resp}")

    raise RuntimeError("GitHub OAuth timed out waiting for user approval")


def _post_form(url: str, data: dict) -> dict:
    """POST application/x-www-form-urlencoded, return parsed JSON body."""
    body = urlencode(data).encode("utf-8")
    req = _urlrequest.Request(
        url,
        data=body,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    with _urlrequest.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode("utf-8"))


# Name → OAuth handler. Add new services here as they're implemented.
_OAUTH_PROVIDERS: dict[str, _TokenProvider] = {
    "github": _github_device_flow,
}


def has_oauth(name: str) -> bool:
    """Return True if ``name`` has a registered OAuth handler."""
    return name in _OAUTH_PROVIDERS


def run_oauth(name: str) -> str:
    """Run the OAuth handler for ``name`` and return the access token."""
    handler = _OAUTH_PROVIDERS.get(name)
    if handler is None:
        raise KeyError(f"No OAuth provider registered for {name!r}")
    return handler()


def register(name: str, handler: _TokenProvider) -> None:
    """Register an OAuth handler. Intended for tests and plugins."""
    _OAUTH_PROVIDERS[name] = handler


def unregister(name: str) -> None:
    """Remove a registered OAuth handler. Intended for tests."""
    _OAUTH_PROVIDERS.pop(name, None)
