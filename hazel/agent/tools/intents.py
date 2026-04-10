"""Intent tools: task/reminder/event/followup management backed by SQLite.

Nine tools for managing intents (tasks, reminders, events, followups) in a
local SQLite database with bidirectional entity linking, RRULE recurrence,
and auto-managed backlinks in entity markdown files.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from loguru import logger

from hazel.agent.tools.base import Tool

# ---------------------------------------------------------------------------
# ULID generation (Crockford Base32, no external dependency)
# ---------------------------------------------------------------------------

_CROCKFORD = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def _generate_ulid() -> str:
    """Generate a ULID (Universally Unique Lexicographically Sortable ID)."""
    ts_ms = int(time.time() * 1000)
    ts_part: list[str] = []
    for _ in range(10):
        ts_part.append(_CROCKFORD[ts_ms & 0x1F])
        ts_ms >>= 5
    ts_part.reverse()

    rand_int = int.from_bytes(os.urandom(10), "big")
    rand_part: list[str] = []
    for _ in range(16):
        rand_part.append(_CROCKFORD[rand_int & 0x1F])
        rand_int >>= 5
    rand_part.reverse()

    return "".join(ts_part) + "".join(rand_part)


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

_db_cache: dict[str, sqlite3.Connection] = {}

_SCHEMA_SQL = """\
CREATE TABLE IF NOT EXISTS intents (
    id TEXT PRIMARY KEY,
    type TEXT NOT NULL CHECK (type IN ('task','reminder','event','followup')),
    title TEXT NOT NULL,
    body TEXT,
    status TEXT NOT NULL CHECK (status IN ('active','done','canceled','snoozed')) DEFAULT 'active',
    priority INTEGER NOT NULL DEFAULT 1,
    estimate_minutes INTEGER,
    timezone TEXT,
    due_at TEXT,
    start_at TEXT,
    end_at TEXT,
    rrule TEXT,
    snooze_until TEXT,
    location_text TEXT,
    attendees_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_fired_at TEXT,
    deferrals INTEGER NOT NULL DEFAULT 0,
    rescheduled_count INTEGER NOT NULL DEFAULT 0
);

CREATE INDEX IF NOT EXISTS idx_intents_status ON intents(status);
CREATE INDEX IF NOT EXISTS idx_intents_due ON intents(due_at);
CREATE INDEX IF NOT EXISTS idx_intents_start ON intents(start_at);
CREATE INDEX IF NOT EXISTS idx_intents_snooze ON intents(snooze_until);
CREATE INDEX IF NOT EXISTS idx_intents_last_fired ON intents(last_fired_at);

CREATE TABLE IF NOT EXISTS intent_links (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    intent_id TEXT NOT NULL,
    entity_id TEXT,
    entity_path TEXT NOT NULL,
    rel TEXT NOT NULL DEFAULT 'relates_to',
    created_at TEXT NOT NULL,
    UNIQUE(intent_id, entity_id, rel),
    FOREIGN KEY(intent_id) REFERENCES intents(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_links_entity_id ON intent_links(entity_id);
CREATE INDEX IF NOT EXISTS idx_links_entity_path ON intent_links(entity_path);
CREATE INDEX IF NOT EXISTS idx_links_intent ON intent_links(intent_id);
"""

# Column migrations for older databases (safe to re-run).
_MIGRATIONS = [
    "ALTER TABLE intent_links ADD COLUMN entity_id TEXT",
    "ALTER TABLE intents ADD COLUMN deferrals INTEGER NOT NULL DEFAULT 0",
    "ALTER TABLE intents ADD COLUMN rescheduled_count INTEGER NOT NULL DEFAULT 0",
]


def _get_db(workspace: Path) -> sqlite3.Connection:
    """Return (or create) a WAL-mode SQLite connection for *workspace*."""
    db_path = str(workspace / "data" / "intents.db")
    if db_path in _db_cache:
        return _db_cache[db_path]

    (workspace / "data").mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA_SQL)

    for stmt in _MIGRATIONS:
        try:
            conn.execute(stmt)
        except sqlite3.OperationalError:
            pass  # column already exists

    conn.commit()
    _db_cache[db_path] = conn
    return conn


def _now_utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_to_dict(row: sqlite3.Row | None) -> dict | None:
    return dict(row) if row is not None else None


def _json_result(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Entity file helpers
# ---------------------------------------------------------------------------


def _resolve_entity_path(workspace: Path, p: str) -> Path:
    path = Path(p)
    return path if path.is_absolute() else (workspace / p).resolve()


def _parse_entity_card(workspace: Path, file_path: str) -> dict[str, str | None] | None:
    """Parse ``<!-- CARD … -->`` from an entity file, returning id + type."""
    try:
        abs_path = _resolve_entity_path(workspace, file_path)
        if not abs_path.exists():
            return None
        content = abs_path.read_text(encoding="utf-8")
        start = content.find("<!-- CARD")
        if start == -1:
            return None
        end = content.find("-->", start)
        if end == -1:
            return None
        block = content[start:end]
        id_m = re.search(r"^\s*id:\s*(.+)\s*$", block, re.MULTILINE)
        type_m = re.search(r"^\s*type:\s*(.+)\s*$", block, re.MULTILINE)
        return {
            "entity_id": id_m.group(1).strip() if id_m else None,
            "entity_type": type_m.group(1).strip() if type_m else None,
        }
    except Exception:
        return None


def _format_due_date(due_at: str | None, start_at: str | None) -> str:
    dt = due_at or start_at
    if not dt:
        return "no date"
    try:
        d = datetime.fromisoformat(dt)
        return d.strftime("%Y-%m-%d %H:%M") + " UTC"
    except (ValueError, TypeError):
        return dt


# ---------------------------------------------------------------------------
# Link helpers
# ---------------------------------------------------------------------------


def _get_links_for_intent(conn: sqlite3.Connection, intent_id: str) -> list[dict]:
    rows = conn.execute(
        "SELECT entity_id, entity_path, rel FROM intent_links WHERE intent_id = ?",
        (intent_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _insert_link(
    conn: sqlite3.Connection,
    workspace: Path,
    intent_id: str,
    entity_path: str,
    rel: str,
    created_at: str,
) -> None:
    card = _parse_entity_card(workspace, entity_path)
    entity_id = card["entity_id"] if card else None
    conn.execute(
        "INSERT OR IGNORE INTO intent_links "
        "(intent_id, entity_id, entity_path, rel, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (intent_id, entity_id, entity_path, rel, created_at),
    )


def _update_entity_backlinks(
    conn: sqlite3.Connection, workspace: Path, entity_path: str
) -> None:
    """Rewrite the ``<!-- INTENTS:AUTO -->`` block in an entity file."""
    try:
        abs_path = _resolve_entity_path(workspace, entity_path)
        if not abs_path.exists():
            return

        card = _parse_entity_card(workspace, entity_path)
        entity_id = card["entity_id"] if card else None

        if entity_id:
            intents = conn.execute(
                "SELECT DISTINCT i.* FROM intents i "
                "JOIN intent_links il ON il.intent_id = i.id "
                "WHERE (il.entity_id = ? OR il.entity_path = ?) "
                "  AND i.status IN ('active', 'snoozed') "
                "ORDER BY COALESCE(i.due_at, i.start_at, i.created_at) ASC "
                "LIMIT 20",
                (entity_id, entity_path),
            ).fetchall()
        else:
            intents = conn.execute(
                "SELECT DISTINCT i.* FROM intents i "
                "JOIN intent_links il ON il.intent_id = i.id "
                "WHERE il.entity_path = ? "
                "  AND i.status IN ('active', 'snoozed') "
                "ORDER BY COALESCE(i.due_at, i.start_at, i.created_at) ASC "
                "LIMIT 20",
                (entity_path,),
            ).fetchall()

        content = abs_path.read_text(encoding="utf-8")

        section_header = "## Linked Intents"
        section_marker = "<!-- INTENTS:AUTO -->"
        section_end = "<!-- /INTENTS:AUTO -->"

        if not intents:
            new_section = ""
        else:
            lines: list[str] = []
            for row in intents:
                i = dict(row)
                sym = "\u23f8" if i["status"] == "snoozed" else "\u2022"
                due = _format_due_date(i["due_at"], i["start_at"])
                lines.append(
                    f"{sym} **{i['type']}** | {i['title']} | {due} | `{i['id']}`"
                )
            new_section = (
                f"{section_header}\n{section_marker}\n"
                + "\n".join(lines)
                + f"\n{section_end}\n"
            )

        m_start = content.find(section_marker)
        m_end = content.find(section_end)

        if m_start != -1 and m_end != -1:
            header_idx = content.rfind(section_header, 0, m_start)
            start_idx = header_idx if header_idx != -1 else m_start
            end_idx = m_end + len(section_end)
            after = content[end_idx:]
            trimmed = after.lstrip("\n") if after.startswith("\n") else after
            content = content[:start_idx] + new_section + trimmed
        elif new_section:
            content = content.rstrip() + "\n\n" + new_section

        abs_path.write_text(content, encoding="utf-8")
    except Exception as err:
        logger.error("Failed to update entity backlinks: {}", err)


def _update_all_backlinks_for_intent(
    conn: sqlite3.Connection, workspace: Path, intent_id: str
) -> None:
    for link in _get_links_for_intent(conn, intent_id):
        _update_entity_backlinks(conn, workspace, link["entity_path"])


# ---------------------------------------------------------------------------
# Recurrence helper
# ---------------------------------------------------------------------------


def _compute_next_occurrence(
    rrule_str: str, after_date: datetime
) -> datetime | None:
    try:
        from dateutil.rrule import rrulestr

        # Ensure after_date is timezone-aware (UTC)
        if after_date.tzinfo is None:
            after_date = after_date.replace(tzinfo=timezone.utc)
        rule = rrulestr(rrule_str, dtstart=after_date)
        return rule.after(after_date, inc=False)
    except Exception:
        return None


# =========================================================================
# Tool implementations
# =========================================================================


class IntentCreateTool(Tool):
    """Create a new intent (task, reminder, event, or followup)."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_create"

    @property
    def description(self) -> str:
        return (
            "Create a new intent (task, reminder, event, or followup). "
            "Returns the created intent with its ULID-based ID. "
            "Optionally link to entity files for bidirectional tracking."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["task", "reminder", "event", "followup"],
                    "description": "Type of intent",
                },
                "title": {
                    "type": "string",
                    "description": "Title of the intent",
                },
                "body": {
                    "type": "string",
                    "description": "Optional body/notes",
                },
                "priority": {
                    "type": "integer",
                    "minimum": 0,
                    "maximum": 3,
                    "description": "Priority 0-3 (default 1)",
                },
                "estimate_minutes": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Estimated duration in minutes",
                },
                "timezone": {
                    "type": "string",
                    "description": "IANA timezone for display, e.g. America/Los_Angeles",
                },
                "due_at": {
                    "type": "string",
                    "description": "UTC ISO8601 timestamp ending in Z",
                },
                "start_at": {
                    "type": "string",
                    "description": "UTC ISO8601 timestamp ending in Z (for events)",
                },
                "end_at": {
                    "type": "string",
                    "description": "UTC ISO8601 timestamp ending in Z (for events)",
                },
                "rrule": {
                    "type": "string",
                    "description": "RFC 5545 RRULE string for recurrence",
                },
                "snooze_until": {
                    "type": "string",
                    "description": "UTC ISO8601 timestamp ending in Z",
                },
                "location_text": {
                    "type": "string",
                    "description": "Location text (for events)",
                },
                "attendees_json": {
                    "type": "string",
                    "description": "JSON string of attendees (for events)",
                },
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entity_path": {"type": "string"},
                            "rel": {"type": "string"},
                        },
                        "required": ["entity_path"],
                    },
                    "description": "Entity paths to link this intent to",
                },
            },
            "required": ["type", "title"],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        now = _now_utc()
        intent_id = _generate_ulid()

        conn.execute(
            "INSERT INTO intents "
            "(id, type, title, body, status, priority, estimate_minutes, timezone, "
            " due_at, start_at, end_at, rrule, snooze_until, location_text, attendees_json, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, 'active', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                intent_id,
                kwargs["type"],
                kwargs["title"],
                kwargs.get("body"),
                kwargs.get("priority", 1),
                kwargs.get("estimate_minutes"),
                kwargs.get("timezone"),
                kwargs.get("due_at"),
                kwargs.get("start_at"),
                kwargs.get("end_at"),
                kwargs.get("rrule"),
                kwargs.get("snooze_until"),
                kwargs.get("location_text"),
                kwargs.get("attendees_json"),
                now,
                now,
            ),
        )

        linked_paths: list[str] = []
        for link in kwargs.get("links") or []:
            entity_path = link["entity_path"]
            _insert_link(
                conn, self._workspace, intent_id, entity_path,
                link.get("rel", "relates_to"), now,
            )
            linked_paths.append(entity_path)

        conn.commit()

        intent = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        links = _get_links_for_intent(conn, intent_id)
        for p in linked_paths:
            _update_entity_backlinks(conn, self._workspace, p)

        return _json_result({"status": "ok", "intent": {**intent, "links": links}})


class IntentUpdateTool(Tool):
    """Update an existing intent. Only provided fields are changed."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_update"

    @property
    def description(self) -> str:
        return "Update an existing intent. Only provided fields are updated."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Intent ID (ULID)"},
                "title": {"type": "string"},
                "body": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["active", "done", "canceled", "snoozed"],
                },
                "priority": {"type": "integer", "minimum": 0, "maximum": 3},
                "estimate_minutes": {"type": "integer", "minimum": 0},
                "timezone": {"type": "string"},
                "due_at": {"type": "string"},
                "start_at": {"type": "string"},
                "end_at": {"type": "string"},
                "rrule": {"type": "string"},
                "snooze_until": {"type": "string"},
                "location_text": {"type": "string"},
                "attendees_json": {"type": "string"},
                "last_fired_at": {"type": "string"},
                "deferrals": {"type": "integer", "minimum": 0},
                "rescheduled_count": {"type": "integer", "minimum": 0},
                "links": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "entity_path": {"type": "string"},
                            "rel": {"type": "string"},
                        },
                        "required": ["entity_path"],
                    },
                    "description": "Replace all entity links (if provided)",
                },
            },
            "required": ["id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        now = _now_utc()
        intent_id = kwargs["id"]

        existing = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        if not existing:
            return _json_result({"status": "error", "error": "Intent not found", "id": intent_id})

        updatable = [
            "title", "body", "status", "priority", "estimate_minutes", "timezone",
            "due_at", "start_at", "end_at", "rrule", "snooze_until",
            "location_text", "attendees_json", "last_fired_at",
            "deferrals", "rescheduled_count",
        ]
        sets: list[str] = []
        vals: list[Any] = []
        for field in updatable:
            if field in kwargs:
                sets.append(f"{field} = ?")
                vals.append(kwargs[field])

        has_link_changes = "links" in kwargs

        if not sets and not has_link_changes:
            return _json_result({"status": "ok", "message": "No fields to update", "intent": existing})

        if sets:
            sets.append("updated_at = ?")
            vals.append(now)
            vals.append(intent_id)
            conn.execute(f"UPDATE intents SET {', '.join(sets)} WHERE id = ?", vals)
        elif has_link_changes:
            conn.execute("UPDATE intents SET updated_at = ? WHERE id = ?", (now, intent_id))

        # Handle link replacement
        if has_link_changes:
            old_links = _get_links_for_intent(conn, intent_id)
            affected_paths = [l["entity_path"] for l in old_links]
            conn.execute("DELETE FROM intent_links WHERE intent_id = ?", (intent_id,))
            for link in kwargs["links"] or []:
                ep = link["entity_path"]
                _insert_link(
                    conn, self._workspace, intent_id, ep,
                    link.get("rel", "relates_to"), now,
                )
                if ep not in affected_paths:
                    affected_paths.append(ep)
            conn.commit()
            for p in affected_paths:
                _update_entity_backlinks(conn, self._workspace, p)
        else:
            conn.commit()

        updated = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        links = _get_links_for_intent(conn, intent_id)

        # If status changed, refresh backlinks
        if "status" in kwargs and kwargs["status"] != existing.get("status"):
            _update_all_backlinks_for_intent(conn, self._workspace, intent_id)

        return _json_result({"status": "ok", "intent": {**updated, "links": links}})


class IntentGetTool(Tool):
    """Get a single intent by ID."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_get"

    @property
    def description(self) -> str:
        return "Get a single intent by ID, including its entity links."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Intent ID (ULID)"},
            },
            "required": ["id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        intent = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (kwargs["id"],)).fetchone()
        )
        if not intent:
            return _json_result({"status": "error", "error": "Intent not found", "id": kwargs["id"]})
        links = _get_links_for_intent(conn, kwargs["id"])
        return _json_result({"status": "ok", "intent": {**intent, "links": links}})


class IntentSearchTool(Tool):
    """Search intents with filters."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_search"

    @property
    def description(self) -> str:
        return (
            "Search intents with filters. Supports text search, "
            "status/type filters, time windows, and entity filtering by path or id."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "q": {
                    "type": "string",
                    "description": "Search query (matches title and body)",
                },
                "status": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["active", "done", "canceled", "snoozed"],
                    },
                },
                "type": {
                    "type": "array",
                    "items": {
                        "type": "string",
                        "enum": ["task", "reminder", "event", "followup"],
                    },
                },
                "due_from": {"type": "string", "description": "UTC ISO8601"},
                "due_to": {"type": "string", "description": "UTC ISO8601"},
                "start_from": {"type": "string", "description": "UTC ISO8601"},
                "start_to": {"type": "string", "description": "UTC ISO8601"},
                "entity_path": {"type": "string", "description": "Filter by linked entity path"},
                "entity_id": {"type": "string", "description": "Filter by linked entity id"},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Max results (default 100)",
                },
                "offset": {
                    "type": "integer",
                    "minimum": 0,
                    "description": "Offset (default 0)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        conditions: list[str] = []
        values: list[Any] = []

        if kwargs.get("q"):
            conditions.append("(intents.title LIKE ? OR intents.body LIKE ?)")
            pattern = f"%{kwargs['q']}%"
            values.extend([pattern, pattern])

        if kwargs.get("status"):
            placeholders = ", ".join("?" for _ in kwargs["status"])
            conditions.append(f"intents.status IN ({placeholders})")
            values.extend(kwargs["status"])

        if kwargs.get("type"):
            placeholders = ", ".join("?" for _ in kwargs["type"])
            conditions.append(f"intents.type IN ({placeholders})")
            values.extend(kwargs["type"])

        if kwargs.get("due_from"):
            conditions.append("intents.due_at >= ?")
            values.append(kwargs["due_from"])
        if kwargs.get("due_to"):
            conditions.append("intents.due_at <= ?")
            values.append(kwargs["due_to"])
        if kwargs.get("start_from"):
            conditions.append("intents.start_at >= ?")
            values.append(kwargs["start_from"])
        if kwargs.get("start_to"):
            conditions.append("intents.start_at <= ?")
            values.append(kwargs["start_to"])

        join_clause = ""
        if kwargs.get("entity_path") or kwargs.get("entity_id"):
            join_clause = "JOIN intent_links il ON il.intent_id = intents.id"
            if kwargs.get("entity_id"):
                conditions.append("il.entity_id = ?")
                values.append(kwargs["entity_id"])
            elif kwargs.get("entity_path"):
                conditions.append("il.entity_path = ?")
                values.append(kwargs["entity_path"])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        limit = kwargs.get("limit", 100)
        offset = kwargs.get("offset", 0)
        values.extend([limit, offset])

        rows = conn.execute(
            f"SELECT DISTINCT intents.* FROM intents {join_clause} {where} "
            "ORDER BY COALESCE(intents.due_at, intents.start_at, intents.created_at) ASC "
            "LIMIT ? OFFSET ?",
            values,
        ).fetchall()

        results = [{**dict(r), "links": _get_links_for_intent(conn, r["id"])} for r in rows]
        return _json_result({"status": "ok", "count": len(results), "intents": results})


class IntentCompleteTool(Tool):
    """Mark an intent as done (or advance recurring intents)."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_complete"

    @property
    def description(self) -> str:
        return (
            "Mark an intent as done. For recurring intents with an rrule, "
            "advances to the next occurrence instead of completing."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Intent ID (ULID)"},
            },
            "required": ["id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        now = _now_utc()
        intent_id = kwargs["id"]

        intent = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        if not intent:
            return _json_result({"status": "error", "error": "Intent not found", "id": intent_id})

        # Handle recurring intents
        if intent.get("rrule") and intent.get("due_at"):
            next_due = _compute_next_occurrence(
                intent["rrule"], datetime.fromisoformat(intent["due_at"])
            )
            if next_due:
                conn.execute(
                    "UPDATE intents SET due_at = ?, updated_at = ?, status = 'active' WHERE id = ?",
                    (next_due.isoformat(), now, intent_id),
                )
                conn.commit()
                updated = _row_to_dict(
                    conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
                )
                _update_all_backlinks_for_intent(conn, self._workspace, intent_id)
                return _json_result({
                    "status": "ok",
                    "message": "Recurring intent advanced to next occurrence",
                    "intent": {**updated, "links": _get_links_for_intent(conn, intent_id)},
                })

        conn.execute(
            "UPDATE intents SET status = 'done', updated_at = ? WHERE id = ?",
            (now, intent_id),
        )
        conn.commit()
        updated = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        _update_all_backlinks_for_intent(conn, self._workspace, intent_id)
        return _json_result({
            "status": "ok",
            "intent": {**updated, "links": _get_links_for_intent(conn, intent_id)},
        })


class IntentSnoozeTool(Tool):
    """Snooze an intent until a specified time."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_snooze"

    @property
    def description(self) -> str:
        return "Snooze an intent until a specified time."

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Intent ID (ULID)"},
                "snooze_until": {
                    "type": "string",
                    "description": "UTC ISO8601 timestamp ending in Z",
                },
            },
            "required": ["id", "snooze_until"],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        now = _now_utc()
        intent_id = kwargs["id"]

        intent = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        if not intent:
            return _json_result({"status": "error", "error": "Intent not found", "id": intent_id})

        conn.execute(
            "UPDATE intents SET snooze_until = ?, status = 'snoozed', updated_at = ? WHERE id = ?",
            (kwargs["snooze_until"], now, intent_id),
        )
        conn.commit()
        updated = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        _update_all_backlinks_for_intent(conn, self._workspace, intent_id)
        return _json_result({
            "status": "ok",
            "intent": {**updated, "links": _get_links_for_intent(conn, intent_id)},
        })


class IntentDeferTool(Tool):
    """Defer an intent by clearing due_at and incrementing deferrals."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_defer"

    @property
    def description(self) -> str:
        return (
            "Defer an intent by clearing its due_at and incrementing the "
            "deferrals counter. Use when the user wants to defer timing "
            "decisions back to the agent."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "id": {"type": "string", "description": "Intent ID (ULID)"},
            },
            "required": ["id"],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        now = _now_utc()
        intent_id = kwargs["id"]

        intent = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        if not intent:
            return _json_result({"status": "error", "error": "Intent not found", "id": intent_id})

        new_deferrals = (intent.get("deferrals") or 0) + 1
        conn.execute(
            "UPDATE intents SET due_at = NULL, deferrals = ?, status = 'active', updated_at = ? WHERE id = ?",
            (new_deferrals, now, intent_id),
        )
        conn.commit()
        updated = _row_to_dict(
            conn.execute("SELECT * FROM intents WHERE id = ?", (intent_id,)).fetchone()
        )
        return _json_result({
            "status": "ok",
            "message": f"Intent deferred ({new_deferrals} total deferrals)",
            "intent": {**updated, "links": _get_links_for_intent(conn, intent_id)},
        })


class IntentListDueTool(Tool):
    """List intents due or active within a time window."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_list_due"

    @property
    def description(self) -> str:
        return (
            "List intents that are due or active within a time window. "
            "Powers agenda queries (now, today, this week, etc.)."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "window_start": {
                    "type": "string",
                    "description": "UTC ISO8601 timestamp ending in Z",
                },
                "window_end": {
                    "type": "string",
                    "description": "UTC ISO8601 timestamp ending in Z",
                },
                "include_overdue": {
                    "type": "boolean",
                    "description": "Include overdue items (default true)",
                },
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 500,
                    "description": "Max results (default 200)",
                },
            },
            "required": ["window_start", "window_end"],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        ws = kwargs["window_start"]
        we = kwargs["window_end"]
        include_overdue = kwargs.get("include_overdue", True)
        limit = kwargs.get("limit", 200)

        if include_overdue:
            sql = (
                "SELECT * FROM intents "
                "WHERE status NOT IN ('done', 'canceled') "
                "  AND (snooze_until IS NULL OR snooze_until <= ?) "
                "  AND ("
                "    (due_at IS NOT NULL AND due_at <= ?)"
                "    OR (start_at IS NOT NULL AND start_at < ? AND (end_at IS NULL OR end_at > ?))"
                "  ) "
                "ORDER BY COALESCE(due_at, start_at) ASC, priority DESC, created_at ASC "
                "LIMIT ?"
            )
            values = [ws, we, we, ws, limit]
        else:
            sql = (
                "SELECT * FROM intents "
                "WHERE status NOT IN ('done', 'canceled') "
                "  AND (snooze_until IS NULL OR snooze_until <= ?) "
                "  AND ("
                "    (due_at IS NOT NULL AND due_at >= ? AND due_at <= ?)"
                "    OR (start_at IS NOT NULL AND start_at < ? AND (end_at IS NULL OR end_at > ?))"
                "  ) "
                "ORDER BY COALESCE(due_at, start_at) ASC, priority DESC, created_at ASC "
                "LIMIT ?"
            )
            values = [ws, ws, we, we, ws, limit]

        rows = conn.execute(sql, values).fetchall()
        results = [{**dict(r), "links": _get_links_for_intent(conn, r["id"])} for r in rows]
        return _json_result({"status": "ok", "count": len(results), "intents": results})


class IntentSyncLinksTool(Tool):
    """Synchronize intent links when entity paths change."""

    def __init__(self, workspace: Path):
        self._workspace = workspace

    @property
    def name(self) -> str:
        return "intent_sync_links"

    @property
    def description(self) -> str:
        return (
            "Synchronize intent links when entity paths change. "
            "Call after renaming/moving entity files."
        )

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "old_path": {
                    "type": "string",
                    "description": "Old entity path to update (if renaming)",
                },
                "new_path": {
                    "type": "string",
                    "description": "New entity path (if renaming)",
                },
                "entity_id": {
                    "type": "string",
                    "description": "Entity ID to sync all links for",
                },
                "refresh_all": {
                    "type": "boolean",
                    "description": "Refresh all links and backlinks (slow)",
                },
            },
            "required": [],
        }

    async def execute(self, **kwargs: Any) -> str:
        conn = _get_db(self._workspace)
        updated = 0

        if kwargs.get("old_path") and kwargs.get("new_path"):
            card = _parse_entity_card(self._workspace, kwargs["new_path"])
            entity_id = card["entity_id"] if card else None
            cur = conn.execute(
                "UPDATE intent_links SET entity_path = ?, "
                "entity_id = COALESCE(?, entity_id) WHERE entity_path = ?",
                (kwargs["new_path"], entity_id, kwargs["old_path"]),
            )
            updated = cur.rowcount
            conn.commit()
            _update_entity_backlinks(conn, self._workspace, kwargs["new_path"])

        if kwargs.get("entity_id"):
            rows = conn.execute(
                "SELECT DISTINCT entity_path FROM intent_links WHERE entity_id = ?",
                (kwargs["entity_id"],),
            ).fetchall()
            for row in rows:
                _update_entity_backlinks(conn, self._workspace, row["entity_path"])
            updated = len(rows)

        if kwargs.get("refresh_all"):
            all_paths = conn.execute(
                "SELECT DISTINCT entity_path FROM intent_links"
            ).fetchall()
            for row in all_paths:
                card = _parse_entity_card(self._workspace, row["entity_path"])
                if card and card.get("entity_id"):
                    conn.execute(
                        "UPDATE intent_links SET entity_id = ? WHERE entity_path = ?",
                        (card["entity_id"], row["entity_path"]),
                    )
                _update_entity_backlinks(conn, self._workspace, row["entity_path"])
            conn.commit()
            updated = len(all_paths)

        return _json_result({"status": "ok", "updated": updated})
