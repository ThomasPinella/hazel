"""Configuration loading utilities."""

import json
import re
from pathlib import Path
from typing import Any

import pydantic
from loguru import logger
from pydantic.alias_generators import to_camel

from hazel.config.schema import Config

# Matches a whole-string reference like "@secret:openweather" (name validated
# by the secrets store). We deliberately only match complete values — not
# embedded substrings — to keep semantics simple and avoid accidental
# partial-replace bugs.
_SECRET_REF_RE = re.compile(r"^@secret:([a-z0-9_-]+)$")

# Global variable to store current config path (for multi-instance support)
_current_config_path: Path | None = None


def set_config_path(path: Path) -> None:
    """Set the current config path (used to derive data directory)."""
    global _current_config_path
    _current_config_path = path


def get_config_path() -> Path:
    """Get the configuration file path."""
    if _current_config_path:
        return _current_config_path
    return Path.home() / ".hazel" / "config.json"


def load_config(config_path: Path | None = None) -> Config:
    """
    Load configuration from file or create default.

    Args:
        config_path: Optional path to config file. Uses default if not provided.

    Returns:
        Loaded configuration object.
    """
    path = config_path or get_config_path()

    if path.exists():
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            data = _migrate_config(data)
            data = _resolve_secret_refs(data)
            return Config.model_validate(data)
        except (json.JSONDecodeError, ValueError, pydantic.ValidationError) as e:
            logger.warning(f"Failed to load config from {path}: {e}")
            logger.warning("Using default configuration.")

    return Config()


def save_config(config: Config, config_path: Path | None = None) -> None:
    """
    Save configuration to file.

    Args:
        config: Configuration to save.
        config_path: Optional path to save to. Uses default if not provided.

    If the target file already contains ``@secret:<name>`` placeholders, they
    are preserved across round-trips — we substitute them back wherever the
    new serialized value still matches the current stored secret value. This
    prevents a load → save cycle from silently materializing plaintext
    credentials into ``config.json``.
    """
    path = config_path or get_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    data = config.model_dump(mode="json", by_alias=True)

    # Preserve @secret: placeholders from the existing file, if any.
    placeholder_paths = _collect_secret_placeholder_paths(path)
    if placeholder_paths:
        _reapply_secret_placeholders(data, placeholder_paths)

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def _collect_secret_placeholder_paths(path: Path) -> dict[tuple, str]:
    """Return a ``{path_tuple → "@secret:name"}`` map from the existing file.

    Path tuples use dict keys and list indices, e.g.
    ``("tools", "web", "search", "apiKey")``. This path-based approach is
    immune to the secret being deleted between load and save: we restore
    the placeholder even when the resolved value is no longer available.

    An unreadable or non-existent file yields an empty map.
    """
    if not path.exists():
        return {}
    try:
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, json.JSONDecodeError):
        return {}

    refs: dict[tuple, str] = {}

    def walk(node: Any, current: tuple) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                # Normalize dict keys to camelCase to match how pydantic
                # will serialize them back out (`model_dump(by_alias=True)`
                # applies `to_camel` via the alias generator). Without this,
                # a user who wrote `api_key` would see the raw path diverge
                # from the serialized path `apiKey`, and we'd fail to
                # restore the placeholder — silently leaking plaintext.
                # Keys that already use camelCase or have no underscores
                # round-trip through `to_camel` unchanged.
                normalized_key = to_camel(k) if isinstance(k, str) else k
                walk(v, current + (normalized_key,))
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, current + (i,))
        elif isinstance(node, str):
            if _SECRET_REF_RE.fullmatch(node):
                refs[current] = node

    walk(raw, ())
    return refs


def _reapply_secret_placeholders(data: Any, paths: dict[tuple, str]) -> None:
    """Restore ``@secret:<name>`` at each recorded path in ``data`` (in place).

    Heuristic:
    - If the field's new serialized value still matches the currently stored
      secret, the user didn't edit it in-memory — restore the placeholder.
    - If the secret is no longer in the store (get_or_none returns None), we
      restore the placeholder anyway. This is the safe-default branch: the
      in-memory value would otherwise be the resolved-at-load plaintext
      value, which we must not write to disk.
    - If the new value differs from the currently stored secret, the user
      intentionally changed it — leave the new value in place.

    Paths that no longer exist (field renamed / removed between schema
    versions) are silently skipped.
    """
    # Lazy import; loader.py is on the hot path of module init.
    from hazel.secrets import get_or_none

    for path_tuple, placeholder in paths.items():
        if not path_tuple:
            continue
        m = _SECRET_REF_RE.fullmatch(placeholder)
        if not m:
            continue
        name = m.group(1)

        node: Any = data
        ok = True
        for key in path_tuple[:-1]:
            if isinstance(node, dict) and key in node:
                node = node[key]
            elif isinstance(node, list) and isinstance(key, int) and 0 <= key < len(node):
                node = node[key]
            else:
                ok = False
                break
        if not ok:
            continue
        last = path_tuple[-1]

        if isinstance(node, dict) and last in node:
            current = node[last]
        elif isinstance(node, list) and isinstance(last, int) and 0 <= last < len(node):
            current = node[last]
        else:
            continue

        stored = get_or_none(name)
        if stored is None or current == stored:
            node[last] = placeholder


def _resolve_secret_refs(data: Any) -> Any:
    """Walk the loaded config and replace ``@secret:<name>`` with stored values.

    - Missing secrets leave the placeholder string in place and emit a
      warning. This allows first-run users who haven't completed OAuth
      flows yet to keep a working config (affected features will degrade
      gracefully when they read an unresolved placeholder).
    - We re-save the placeholder verbatim so subsequent ``save_config``
      round-trips don't overwrite the reference with a blank string.
    """
    # Imported lazily to avoid a circular import (secrets.store imports
    # config.paths, which currently imports config.loader indirectly via
    # lazy helpers).
    from hazel.secrets import get_or_none

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v) for v in node]
        if isinstance(node, str):
            m = _SECRET_REF_RE.fullmatch(node)
            if m:
                name = m.group(1)
                # get_or_none avoids a TOCTOU exists()/get() race and folds
                # any missing-file case into a single check.
                value = get_or_none(name)
                if value is not None:
                    return value
                logger.warning(
                    "Secret reference @secret:{} unresolved — run `hazel auth {}` to set it",
                    name, name,
                )
                return node
        return node

    return walk(data)


def _migrate_config(data: dict) -> dict:
    """Migrate old config formats to current."""
    # Move tools.exec.restrictToWorkspace → tools.restrictToWorkspace
    tools = data.get("tools", {})
    exec_cfg = tools.get("exec", {})
    if "restrictToWorkspace" in exec_cfg and "restrictToWorkspace" not in tools:
        tools["restrictToWorkspace"] = exec_cfg.pop("restrictToWorkspace")
    return data
