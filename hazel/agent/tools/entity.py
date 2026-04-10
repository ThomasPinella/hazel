"""Entity memory tools: record_change, query_changes, retrieve_entities."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any

from loguru import logger

from hazel.agent.tools.base import Tool

if TYPE_CHECKING:
    from hazel.providers.base import LLMProvider


def _now_iso_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _yyyy_mm_dd(iso: str) -> str:
    return iso[:10]


def _parse_card_header(md: str) -> dict[str, Any]:
    """Parse CARD header from markdown content."""
    start = md.find("<!-- CARD")
    if start == -1:
        return {}
    end = md.find("-->", start)
    if end == -1:
        return {}
    block = md[start:end]

    import re

    result: dict[str, Any] = {}
    id_m = re.search(r"^\s*id:\s*(.+)\s*$", block, re.MULTILINE)
    type_m = re.search(r"^\s*type:\s*(.+)\s*$", block, re.MULTILINE)
    tags_m = re.search(r"^\s*tags:\s*(.+)\s*$", block, re.MULTILINE)

    if id_m:
        result["entity_id"] = id_m.group(1).strip()
    if type_m:
        result["entity_type"] = type_m.group(1).strip()
    if tags_m:
        try:
            tags = json.loads(tags_m.group(1).strip())
            if isinstance(tags, list):
                result["tags"] = tags
        except (json.JSONDecodeError, ValueError):
            pass
    return result


def _read_jsonl(path: Path) -> list[dict]:
    """Read JSONL file, returning list of parsed objects."""
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def _append_jsonl(path: Path, obj: dict) -> None:
    """Append a JSON object as a line to a JSONL file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def _within_seconds(a: str, b: str, sec: int) -> bool:
    """Check if two ISO timestamps are within `sec` seconds of each other."""
    try:
        ta = datetime.fromisoformat(a).timestamp()
        tb = datetime.fromisoformat(b).timestamp()
        return abs(ta - tb) <= sec
    except (ValueError, TypeError):
        return False


def _parse_date_or_iso(s: str | None) -> float | None:
    """Parse a date string (YYYY-MM-DD) or ISO timestamp to epoch seconds."""
    if not s:
        return None
    try:
        if len(s) == 10 and s[4] == "-" and s[7] == "-":
            return datetime.fromisoformat(s + "T00:00:00+00:00").timestamp()
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# record_change
# ---------------------------------------------------------------------------

class RecordChangeTool(Tool):
    """Append a structured change record to memory/_index/changes.jsonl."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    def _ledger_path(self) -> Path:
        return self._workspace / "memory" / "_index" / "changes.jsonl"

    def _resolve(self, path: str) -> Path:
        p = Path(path)
        if not p.is_absolute():
            p = self._workspace / p
        return p.resolve()

    @property
    def name(self) -> str:
        return "record_change"

    @property
    def description(self) -> str:
        return (
            "Append one structured change record to memory/_index/changes.jsonl "
            "after creating or updating an entity file under memory/areas/**. "
            "If entity_id/entity_type/tags are omitted, they are parsed from the "
            "file's CARD header."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "op": {
                    "type": "string",
                    "enum": ["create", "update"],
                    "description": "Whether the entity was created or updated",
                },
                "path": {
                    "type": "string",
                    "description": "Path to the entity file, e.g. memory/areas/projects/hazel.md",
                },
                "reason": {
                    "type": "string",
                    "enum": ["runtime", "daily_compress", "manual", "import"],
                    "description": "Why the change was made",
                },
                "source": {
                    "type": "string",
                    "description": "Optional source pointer, e.g. memory/2026-01-27.md",
                },
                "summary": {
                    "type": "string",
                    "description": "Optional 1-sentence description of what changed",
                },
                "entity_id": {"type": "string"},
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "place", "project", "domain", "resource", "system"],
                },
                "tags": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "dedupe_seconds": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 60,
                    "description": "Deduplication window in seconds (default 5)",
                },
            },
            "required": ["op", "path", "reason"],
        }

    async def execute(self, **kwargs: Any) -> str:
        ledger = self._ledger_path()
        ts = _now_iso_utc()
        date = _yyyy_mm_dd(ts)

        entity_id = kwargs.get("entity_id")
        entity_type = kwargs.get("entity_type")
        tags = kwargs.get("tags")

        # Auto-parse CARD header if fields missing
        if not entity_id or not entity_type or tags is None:
            try:
                entity_file = self._resolve(kwargs["path"])
                md = entity_file.read_text(encoding="utf-8")
                card = _parse_card_header(md)
                entity_id = entity_id or card.get("entity_id")
                entity_type = entity_type or card.get("entity_type")
                if tags is None:
                    tags = card.get("tags")
            except (OSError, UnicodeDecodeError):
                pass

        row = {
            "ts": ts,
            "date": date,
            "op": kwargs["op"],
            "path": kwargs["path"],
            "entity_id": entity_id,
            "entity_type": entity_type,
            "reason": kwargs["reason"],
            "source": kwargs.get("source"),
            "summary": kwargs.get("summary"),
            "tags": tags,
        }

        # Dedupe check
        dedupe_seconds = kwargs.get("dedupe_seconds", 5)
        if dedupe_seconds > 0 and ledger.exists():
            rows = _read_jsonl(ledger)
            if rows:
                last = rows[-1]
                if (
                    last.get("path") == row["path"]
                    and last.get("op") == row["op"]
                    and last.get("reason") == row["reason"]
                    and last.get("source") == row.get("source")
                    and isinstance(last.get("ts"), str)
                    and _within_seconds(last["ts"], row["ts"], dedupe_seconds)
                ):
                    return json.dumps({
                        "status": "ok",
                        "written": False,
                        "deduped": True,
                        "path": "memory/_index/changes.jsonl",
                    })

        _append_jsonl(ledger, row)
        return json.dumps({
            "status": "ok",
            "written": True,
            "path": "memory/_index/changes.jsonl",
        })


# ---------------------------------------------------------------------------
# query_changes
# ---------------------------------------------------------------------------

class QueryChangesTool(Tool):
    """Query the change ledger deterministically."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    def _ledger_path(self) -> Path:
        return self._workspace / "memory" / "_index" / "changes.jsonl"

    @property
    def name(self) -> str:
        return "query_changes"

    @property
    def description(self) -> str:
        return (
            "Query structured change records from memory/_index/changes.jsonl. "
            "Supports time windows, entity filters, and path prefix matching. "
            "Returns matching rows sorted by timestamp."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "since": {
                    "type": "string",
                    "description": "YYYY-MM-DD or ISO-8601 (inclusive). If date, treated as UTC midnight.",
                },
                "until": {
                    "type": "string",
                    "description": "YYYY-MM-DD or ISO-8601 (exclusive). If date, treated as UTC midnight.",
                },
                "entity_id": {"type": "string"},
                "entity_type": {
                    "type": "string",
                    "enum": ["person", "place", "project", "domain", "resource", "system"],
                },
                "path_prefix": {
                    "type": "string",
                    "description": "Only rows whose path starts with this prefix, e.g. memory/areas/",
                },
                "reason": {
                    "type": "string",
                    "enum": ["runtime", "daily_compress", "manual", "import"],
                },
                "op": {
                    "type": "string",
                    "enum": ["create", "update"],
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 5000,
                    "description": "Max rows to return (default 100)",
                },
                "sort": {
                    "type": "string",
                    "enum": ["asc", "desc"],
                    "description": "Sort order by timestamp (default desc)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        all_rows = _read_jsonl(self._ledger_path())
        since_t = _parse_date_or_iso(kwargs.get("since"))
        until_t = _parse_date_or_iso(kwargs.get("until"))
        sort_dir = kwargs.get("sort", "desc")
        limit = kwargs.get("limit", 100)

        filtered = []
        for r in all_rows:
            if not isinstance(r, dict):
                continue
            # Time filter
            if since_t is not None or until_t is not None:
                ts_str = r.get("ts")
                if not isinstance(ts_str, str):
                    continue
                t = _parse_date_or_iso(ts_str)
                if t is None:
                    continue
                if since_t is not None and t < since_t:
                    continue
                if until_t is not None and t >= until_t:
                    continue
            if kwargs.get("entity_id") and r.get("entity_id") != kwargs["entity_id"]:
                continue
            if kwargs.get("entity_type") and r.get("entity_type") != kwargs["entity_type"]:
                continue
            if kwargs.get("reason") and r.get("reason") != kwargs["reason"]:
                continue
            if kwargs.get("op") and r.get("op") != kwargs["op"]:
                continue
            prefix = kwargs.get("path_prefix")
            if prefix and not (isinstance(r.get("path"), str) and r["path"].startswith(prefix)):
                continue
            filtered.append(r)

        def _sort_key(row: dict) -> float:
            t = _parse_date_or_iso(row.get("ts"))
            return t if t is not None else 0.0

        filtered.sort(key=_sort_key, reverse=(sort_dir == "desc"))
        rows = filtered[:limit]
        return json.dumps({"count": len(rows), "rows": rows})


# ---------------------------------------------------------------------------
# retrieve_entities
# ---------------------------------------------------------------------------

class RetrieveEntitiesTool(Tool):
    """LLM-based CARD routing to find relevant entity files."""

    def __init__(self, workspace: Path, provider: LLMProvider, model: str):
        self._workspace = workspace
        self._provider = provider
        self._model = model

    @property
    def name(self) -> str:
        return "retrieve_entities"

    @property
    def description(self) -> str:
        return (
            "Find relevant entity files for a query using LLM-based CARD routing. "
            "Returns file paths only. Use this before read_file to find which entities "
            "are relevant to a question. The retrieval happens in isolation — CARD "
            "contents do not enter your main context."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The question or topic to find relevant entities for",
                },
                "count": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 20,
                    "description": "Number of entities to return (default 10)",
                },
                "context": {
                    "type": "string",
                    "description": "Optional additional context to improve relevance",
                },
            },
            "required": ["query"],
        }

    def _generate_cards_index(self) -> str:
        """Scan memory/areas/ for entity files with CARD headers."""
        areas_dir = self._workspace / "memory" / "areas"
        if not areas_dir.exists():
            return ""

        output = "# Entity Cards Index\n\n"
        for md_file in sorted(areas_dir.rglob("*.md")):
            try:
                content = md_file.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            import re
            card_match = re.search(r"<!--\s*CARD[\s\S]*?-->", content)
            if card_match:
                rel_path = md_file.relative_to(self._workspace)
                output += f"## {rel_path}\n\n{card_match.group()}\n\n---\n\n"
        return output

    @staticmethod
    def _parse_paths_from_response(response: str) -> list[str]:
        """Extract file paths from LLM response."""
        import re
        # Try JSON array first
        json_match = re.search(r"\[[\s\S]*?\]", response)
        if json_match:
            try:
                parsed = json.loads(json_match.group())
                if isinstance(parsed, list):
                    return [p for p in parsed if isinstance(p, str)]
            except json.JSONDecodeError:
                pass
        # Fallback: extract paths line by line
        paths = []
        for line in response.splitlines():
            match = re.search(r"memory/areas/[^\s\"',\]]+\.md", line)
            if match:
                paths.append(match.group())
        return paths

    async def execute(self, **kwargs: Any) -> str:
        query = kwargs["query"]
        count = kwargs.get("count", 10)
        context = kwargs.get("context")

        cards = self._generate_cards_index()
        if not cards or len(cards.strip()) < 100:
            return json.dumps({
                "status": "error",
                "error": "No entity cards found. Create entities in memory/areas/ first.",
                "paths": [],
            })

        prompt = (
            "You are an entity retrieval system. Find the most relevant entity files for a query.\n\n"
            f"USER QUERY: {query}\n"
        )
        if context:
            prompt += f"\nCONTEXT:\n{context}\n"
        prompt += (
            f"\nCARDS INDEX:\n{cards}\n"
            f"Select the top {count} most relevant entities. "
            "Return ONLY a JSON array of file paths, most relevant first.\n"
            'Example: ["memory/areas/topics/example.md", "memory/areas/people/someone.md"]'
        )

        messages = [{"role": "user", "content": prompt}]

        try:
            response = await self._provider.chat_with_retry(
                messages=messages,
                tools=None,
                model=self._model,
                temperature=0.1,
                max_tokens=2048,
            )

            if response.finish_reason == "error":
                return json.dumps({
                    "status": "error",
                    "error": response.content or "LLM call failed",
                    "paths": [],
                })

            paths = self._parse_paths_from_response(response.content or "")
            return json.dumps({
                "status": "ok",
                "query": query,
                "count": len(paths),
                "paths": paths,
            })
        except Exception as exc:
            logger.error("retrieve_entities failed: {}", exc)
            return json.dumps({
                "status": "error",
                "error": str(exc),
                "paths": [],
            })
