"""Runtime path helpers derived from the active config context."""

from __future__ import annotations

import os
from pathlib import Path

from hazel.config.loader import get_config_path
from hazel.utils.helpers import ensure_dir


def get_data_dir() -> Path:
    """Return the instance-level runtime data directory."""
    return ensure_dir(get_config_path().parent)


def get_runtime_subdir(name: str) -> Path:
    """Return a named runtime subdirectory under the instance data dir."""
    return ensure_dir(get_data_dir() / name)


def get_media_dir(channel: str | None = None) -> Path:
    """Return the media directory, optionally namespaced per channel."""
    base = get_runtime_subdir("media")
    return ensure_dir(base / channel) if channel else base


def get_cron_dir() -> Path:
    """Return the cron storage directory."""
    return get_runtime_subdir("cron")


def get_logs_dir() -> Path:
    """Return the logs directory."""
    return get_runtime_subdir("logs")


def get_workspace_path(workspace: str | None = None) -> Path:
    """Resolve and ensure the agent workspace path."""
    path = Path(workspace).expanduser() if workspace else Path.home() / ".hazel" / "workspace"
    return ensure_dir(path)


def get_cli_history_path() -> Path:
    """Return the shared CLI history file path."""
    return Path.home() / ".hazel" / "history" / "cli_history"


def get_bridge_install_dir() -> Path:
    """Return the shared WhatsApp bridge installation directory."""
    return Path.home() / ".hazel" / "bridge"


def get_legacy_sessions_dir() -> Path:
    """Return the legacy global session directory used for migration fallback."""
    return Path.home() / ".hazel" / "sessions"


def get_secrets_dir() -> Path:
    """Return the unified secrets directory (``~/.hazel/secrets``, chmod 0700).

    Secrets are shared across Hazel instances on a machine so that OAuth
    tokens and API keys don't have to be re-authed per config. The directory
    is chmod'd to ``0700`` on every access to repair accidental perm changes.
    """
    d = Path.home() / ".hazel" / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        # Windows / non-POSIX: best effort only
        pass
    return d


def get_pending_setup_skills_path() -> Path:
    """Return the path for saved pending skills setup instructions."""
    return get_data_dir() / "pending_setup_skills.md"


def get_pending_setup_user_actions_path() -> Path:
    """Return the path for saved pending user-actions setup instructions."""
    return get_data_dir() / "pending_setup_user_actions.md"
