"""Tests for the intent tools (task/reminder/event/followup management)."""

import json
from pathlib import Path

import pytest

from hazel.agent.tools.intents import (
    IntentCompleteTool,
    IntentCreateTool,
    IntentDeferTool,
    IntentGetTool,
    IntentListDueTool,
    IntentSearchTool,
    IntentSnoozeTool,
    IntentSyncLinksTool,
    IntentUpdateTool,
    _compute_next_occurrence,
    _format_due_date,
    _generate_ulid,
    _get_db,
    _parse_entity_card,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_entity_file(ws: Path, rel_path: str, card_id: str, card_type: str) -> Path:
    """Create a minimal entity file with a CARD header."""
    p = ws / rel_path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"<!-- CARD\nid: {card_id}\ntype: {card_type}\n"
        f'gist: Test entity\ntags: ["test"]\n-->\n\n# Entity\n',
        encoding="utf-8",
    )
    return p


# ---------------------------------------------------------------------------
# ULID generation
# ---------------------------------------------------------------------------


class TestUlidGeneration:
    def test_length_is_26(self):
        assert len(_generate_ulid()) == 26

    def test_unique_ids(self):
        ids = {_generate_ulid() for _ in range(100)}
        assert len(ids) == 100

    def test_crockford_alphabet(self):
        valid = set("0123456789ABCDEFGHJKMNPQRSTVWXYZ")
        for _ in range(10):
            assert set(_generate_ulid()).issubset(valid)

    def test_sortable_by_time(self):
        import time

        a = _generate_ulid()
        time.sleep(0.002)
        b = _generate_ulid()
        assert a < b


# ---------------------------------------------------------------------------
# Database initialization
# ---------------------------------------------------------------------------


class TestDatabase:
    def test_db_created_on_first_access(self, tmp_path):
        conn = _get_db(tmp_path)
        assert (tmp_path / "data" / "intents.db").exists()
        # Tables exist
        tables = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert "intents" in tables
        assert "intent_links" in tables

    def test_db_cached_across_calls(self, tmp_path):
        conn1 = _get_db(tmp_path)
        conn2 = _get_db(tmp_path)
        assert conn1 is conn2

    def test_wal_mode(self, tmp_path):
        conn = _get_db(tmp_path)
        mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_format_due_date_with_value(self):
        assert "2026-04-01 10:00 UTC" == _format_due_date("2026-04-01T10:00:00Z", None)

    def test_format_due_date_falls_back_to_start(self):
        result = _format_due_date(None, "2026-04-01T09:00:00Z")
        assert "2026-04-01" in result

    def test_format_due_date_none(self):
        assert _format_due_date(None, None) == "no date"

    def test_parse_entity_card(self, tmp_path):
        _make_entity_file(tmp_path, "memory/areas/people/alice.md", "person_alice", "person")
        card = _parse_entity_card(tmp_path, "memory/areas/people/alice.md")
        assert card is not None
        assert card["entity_id"] == "person_alice"
        assert card["entity_type"] == "person"

    def test_parse_entity_card_missing_file(self, tmp_path):
        assert _parse_entity_card(tmp_path, "nonexistent.md") is None

    def test_parse_entity_card_no_card_header(self, tmp_path):
        f = tmp_path / "plain.md"
        f.write_text("# No CARD header here\n")
        assert _parse_entity_card(tmp_path, "plain.md") is None


# ---------------------------------------------------------------------------
# Recurrence
# ---------------------------------------------------------------------------


class TestRecurrence:
    def test_weekly_rrule(self):
        from datetime import datetime, timezone

        dt = datetime(2026, 3, 27, 10, 0, 0, tzinfo=timezone.utc)
        nxt = _compute_next_occurrence("RRULE:FREQ=WEEKLY;BYDAY=TH", dt)
        assert nxt is not None
        assert nxt > dt
        assert nxt.weekday() == 3  # Thursday

    def test_daily_rrule(self):
        from datetime import datetime, timezone

        dt = datetime(2026, 3, 27, 8, 0, 0, tzinfo=timezone.utc)
        nxt = _compute_next_occurrence("FREQ=DAILY", dt)
        assert nxt is not None
        assert nxt.day == 28

    def test_invalid_rrule_returns_none(self):
        from datetime import datetime, timezone

        dt = datetime(2026, 3, 27, 10, 0, 0, tzinfo=timezone.utc)
        assert _compute_next_occurrence("NOT_A_VALID_RRULE", dt) is None


# ---------------------------------------------------------------------------
# intent_create
# ---------------------------------------------------------------------------


class TestIntentCreate:
    @pytest.fixture()
    def tool(self, tmp_path):
        return IntentCreateTool(tmp_path)

    async def test_basic_create(self, tool):
        r = json.loads(await tool.execute(type="task", title="Buy milk"))
        assert r["status"] == "ok"
        assert r["intent"]["type"] == "task"
        assert r["intent"]["title"] == "Buy milk"
        assert r["intent"]["status"] == "active"
        assert len(r["intent"]["id"]) == 26

    async def test_create_with_all_fields(self, tool):
        r = json.loads(
            await tool.execute(
                type="event",
                title="Team meeting",
                body="Quarterly sync",
                priority=3,
                estimate_minutes=60,
                timezone="America/New_York",
                due_at="2026-04-01T14:00:00Z",
                start_at="2026-04-01T14:00:00Z",
                end_at="2026-04-01T15:00:00Z",
                location_text="Conference Room B",
                attendees_json='["alice", "bob"]',
            )
        )
        intent = r["intent"]
        assert intent["priority"] == 3
        assert intent["estimate_minutes"] == 60
        assert intent["location_text"] == "Conference Room B"
        assert intent["start_at"] == "2026-04-01T14:00:00Z"
        assert intent["end_at"] == "2026-04-01T15:00:00Z"

    async def test_create_with_entity_links(self, tmp_path):
        _make_entity_file(
            tmp_path, "memory/areas/people/bob.md", "person_bob", "person"
        )
        tool = IntentCreateTool(tmp_path)
        r = json.loads(
            await tool.execute(
                type="followup",
                title="Follow up with Bob",
                links=[{"entity_path": "memory/areas/people/bob.md", "rel": "assigned_to"}],
            )
        )
        assert len(r["intent"]["links"]) == 1
        assert r["intent"]["links"][0]["entity_id"] == "person_bob"
        assert r["intent"]["links"][0]["rel"] == "assigned_to"

    async def test_create_writes_backlinks(self, tmp_path):
        entity = _make_entity_file(
            tmp_path, "memory/areas/people/carol.md", "person_carol", "person"
        )
        tool = IntentCreateTool(tmp_path)
        await tool.execute(
            type="task",
            title="Review Carol's PR",
            due_at="2026-04-01T10:00:00Z",
            links=[{"entity_path": "memory/areas/people/carol.md"}],
        )
        content = entity.read_text()
        assert "<!-- INTENTS:AUTO -->" in content
        assert "Review Carol's PR" in content
        assert "<!-- /INTENTS:AUTO -->" in content

    async def test_default_priority(self, tool):
        r = json.loads(await tool.execute(type="reminder", title="Test"))
        assert r["intent"]["priority"] == 1

    async def test_default_status(self, tool):
        r = json.loads(await tool.execute(type="task", title="Test"))
        assert r["intent"]["status"] == "active"


# ---------------------------------------------------------------------------
# intent_get
# ---------------------------------------------------------------------------


class TestIntentGet:
    async def test_get_existing(self, tmp_path):
        create = IntentCreateTool(tmp_path)
        r = json.loads(await create.execute(type="task", title="Test"))
        intent_id = r["intent"]["id"]

        get = IntentGetTool(tmp_path)
        r2 = json.loads(await get.execute(id=intent_id))
        assert r2["status"] == "ok"
        assert r2["intent"]["id"] == intent_id
        assert r2["intent"]["title"] == "Test"

    async def test_get_not_found(self, tmp_path):
        get = IntentGetTool(tmp_path)
        r = json.loads(await get.execute(id="NONEXISTENT00000000000000"))
        assert r["status"] == "error"
        assert "not found" in r["error"].lower()


# ---------------------------------------------------------------------------
# intent_update
# ---------------------------------------------------------------------------


class TestIntentUpdate:
    async def _create(self, ws, **kw):
        r = json.loads(await IntentCreateTool(ws).execute(**kw))
        return r["intent"]["id"]

    async def test_update_title(self, tmp_path):
        iid = await self._create(tmp_path, type="task", title="Old")
        r = json.loads(await IntentUpdateTool(tmp_path).execute(id=iid, title="New"))
        assert r["intent"]["title"] == "New"

    async def test_update_status(self, tmp_path):
        iid = await self._create(tmp_path, type="task", title="Test")
        r = json.loads(
            await IntentUpdateTool(tmp_path).execute(id=iid, status="canceled")
        )
        assert r["intent"]["status"] == "canceled"

    async def test_update_multiple_fields(self, tmp_path):
        iid = await self._create(tmp_path, type="task", title="Test", priority=1)
        r = json.loads(
            await IntentUpdateTool(tmp_path).execute(
                id=iid, priority=3, body="Updated notes"
            )
        )
        assert r["intent"]["priority"] == 3
        assert r["intent"]["body"] == "Updated notes"

    async def test_update_no_fields(self, tmp_path):
        iid = await self._create(tmp_path, type="task", title="Test")
        r = json.loads(await IntentUpdateTool(tmp_path).execute(id=iid))
        assert r["status"] == "ok"
        assert r["message"] == "No fields to update"

    async def test_update_not_found(self, tmp_path):
        r = json.loads(
            await IntentUpdateTool(tmp_path).execute(
                id="NONEXISTENT00000000000000", title="X"
            )
        )
        assert r["status"] == "error"

    async def test_update_replaces_links(self, tmp_path):
        _make_entity_file(
            tmp_path, "memory/areas/people/a.md", "person_a", "person"
        )
        _make_entity_file(
            tmp_path, "memory/areas/people/b.md", "person_b", "person"
        )
        iid = await self._create(
            tmp_path,
            type="task",
            title="Test",
            links=[{"entity_path": "memory/areas/people/a.md"}],
        )
        r = json.loads(
            await IntentUpdateTool(tmp_path).execute(
                id=iid, links=[{"entity_path": "memory/areas/people/b.md"}]
            )
        )
        assert len(r["intent"]["links"]) == 1
        assert r["intent"]["links"][0]["entity_id"] == "person_b"


# ---------------------------------------------------------------------------
# intent_search
# ---------------------------------------------------------------------------


class TestIntentSearch:
    async def _create(self, ws, **kw):
        return json.loads(await IntentCreateTool(ws).execute(**kw))

    async def test_search_by_text(self, tmp_path):
        await self._create(tmp_path, type="task", title="Buy groceries")
        await self._create(tmp_path, type="task", title="Clean house")
        r = json.loads(await IntentSearchTool(tmp_path).execute(q="groceries"))
        assert r["count"] == 1
        assert r["intents"][0]["title"] == "Buy groceries"

    async def test_search_by_status(self, tmp_path):
        r1 = await self._create(tmp_path, type="task", title="A")
        await IntentCompleteTool(tmp_path).execute(id=r1["intent"]["id"])
        await self._create(tmp_path, type="task", title="B")
        r = json.loads(
            await IntentSearchTool(tmp_path).execute(status=["active"])
        )
        assert r["count"] == 1
        assert r["intents"][0]["title"] == "B"

    async def test_search_by_type(self, tmp_path):
        await self._create(tmp_path, type="task", title="A")
        await self._create(tmp_path, type="reminder", title="B")
        await self._create(tmp_path, type="event", title="C")
        r = json.loads(
            await IntentSearchTool(tmp_path).execute(type=["reminder", "event"])
        )
        assert r["count"] == 2

    async def test_search_by_due_window(self, tmp_path):
        await self._create(
            tmp_path, type="task", title="Early", due_at="2026-03-01T00:00:00Z"
        )
        await self._create(
            tmp_path, type="task", title="Mid", due_at="2026-03-15T00:00:00Z"
        )
        await self._create(
            tmp_path, type="task", title="Late", due_at="2026-03-31T00:00:00Z"
        )
        r = json.loads(
            await IntentSearchTool(tmp_path).execute(
                due_from="2026-03-10T00:00:00Z", due_to="2026-03-20T00:00:00Z"
            )
        )
        assert r["count"] == 1
        assert r["intents"][0]["title"] == "Mid"

    async def test_search_by_entity(self, tmp_path):
        _make_entity_file(
            tmp_path, "memory/areas/people/dave.md", "person_dave", "person"
        )
        await self._create(
            tmp_path,
            type="task",
            title="With entity",
            links=[{"entity_path": "memory/areas/people/dave.md"}],
        )
        await self._create(tmp_path, type="task", title="Without entity")
        r = json.loads(
            await IntentSearchTool(tmp_path).execute(entity_id="person_dave")
        )
        assert r["count"] == 1
        assert r["intents"][0]["title"] == "With entity"

    async def test_search_limit_and_offset(self, tmp_path):
        for i in range(5):
            await self._create(
                tmp_path,
                type="task",
                title=f"Task {i}",
                due_at=f"2026-04-0{i+1}T00:00:00Z",
            )
        r = json.loads(
            await IntentSearchTool(tmp_path).execute(limit=2, offset=1)
        )
        assert r["count"] == 2

    async def test_search_no_filters_returns_all(self, tmp_path):
        await self._create(tmp_path, type="task", title="A")
        await self._create(tmp_path, type="reminder", title="B")
        r = json.loads(await IntentSearchTool(tmp_path).execute())
        assert r["count"] == 2


# ---------------------------------------------------------------------------
# intent_complete
# ---------------------------------------------------------------------------


class TestIntentComplete:
    async def test_simple_complete(self, tmp_path):
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(type="task", title="Done")
        )
        iid = r["intent"]["id"]
        r2 = json.loads(await IntentCompleteTool(tmp_path).execute(id=iid))
        assert r2["intent"]["status"] == "done"

    async def test_complete_advances_recurring(self, tmp_path):
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(
                type="task",
                title="Weekly",
                due_at="2026-03-27T10:00:00Z",
                rrule="RRULE:FREQ=WEEKLY;BYDAY=TH",
            )
        )
        iid = r["intent"]["id"]
        r2 = json.loads(await IntentCompleteTool(tmp_path).execute(id=iid))
        assert r2["intent"]["status"] == "active"
        assert "next occurrence" in r2["message"].lower()
        # Due date should have advanced
        assert r2["intent"]["due_at"] != "2026-03-27T10:00:00Z"

    async def test_complete_not_found(self, tmp_path):
        r = json.loads(
            await IntentCompleteTool(tmp_path).execute(
                id="NONEXISTENT00000000000000"
            )
        )
        assert r["status"] == "error"

    async def test_complete_updates_backlinks(self, tmp_path):
        entity = _make_entity_file(
            tmp_path, "memory/areas/people/eve.md", "person_eve", "person"
        )
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(
                type="task",
                title="Eve task",
                due_at="2026-04-01T10:00:00Z",
                links=[{"entity_path": "memory/areas/people/eve.md"}],
            )
        )
        # Backlink should be present before completion
        assert "Eve task" in entity.read_text()

        await IntentCompleteTool(tmp_path).execute(id=r["intent"]["id"])
        # After completion, the backlink section should be cleared (done intents excluded)
        content = entity.read_text()
        assert "Eve task" not in content


# ---------------------------------------------------------------------------
# intent_snooze
# ---------------------------------------------------------------------------


class TestIntentSnooze:
    async def test_snooze(self, tmp_path):
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(type="task", title="Snooze me")
        )
        iid = r["intent"]["id"]
        r2 = json.loads(
            await IntentSnoozeTool(tmp_path).execute(
                id=iid, snooze_until="2026-04-05T08:00:00Z"
            )
        )
        assert r2["intent"]["status"] == "snoozed"
        assert r2["intent"]["snooze_until"] == "2026-04-05T08:00:00Z"

    async def test_snooze_not_found(self, tmp_path):
        r = json.loads(
            await IntentSnoozeTool(tmp_path).execute(
                id="NONEXISTENT00000000000000",
                snooze_until="2026-04-05T08:00:00Z",
            )
        )
        assert r["status"] == "error"


# ---------------------------------------------------------------------------
# intent_defer
# ---------------------------------------------------------------------------


class TestIntentDefer:
    async def test_defer_clears_due_and_increments(self, tmp_path):
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(
                type="task", title="Defer me", due_at="2026-04-01T10:00:00Z"
            )
        )
        iid = r["intent"]["id"]
        r2 = json.loads(await IntentDeferTool(tmp_path).execute(id=iid))
        assert r2["intent"]["due_at"] is None
        assert r2["intent"]["deferrals"] == 1
        assert r2["intent"]["status"] == "active"

    async def test_defer_increments_each_call(self, tmp_path):
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(
                type="task", title="Multi defer", due_at="2026-04-01T10:00:00Z"
            )
        )
        iid = r["intent"]["id"]
        await IntentDeferTool(tmp_path).execute(id=iid)
        # Re-set due_at to defer again
        await IntentUpdateTool(tmp_path).execute(
            id=iid, due_at="2026-04-02T10:00:00Z"
        )
        r3 = json.loads(await IntentDeferTool(tmp_path).execute(id=iid))
        assert r3["intent"]["deferrals"] == 2

    async def test_defer_not_found(self, tmp_path):
        r = json.loads(
            await IntentDeferTool(tmp_path).execute(
                id="NONEXISTENT00000000000000"
            )
        )
        assert r["status"] == "error"


# ---------------------------------------------------------------------------
# intent_list_due
# ---------------------------------------------------------------------------


class TestIntentListDue:
    async def _create(self, ws, **kw):
        return json.loads(await IntentCreateTool(ws).execute(**kw))

    async def test_items_in_window(self, tmp_path):
        await self._create(
            tmp_path, type="task", title="In window", due_at="2026-03-28T12:00:00Z"
        )
        await self._create(
            tmp_path, type="task", title="Outside", due_at="2026-04-15T12:00:00Z"
        )
        r = json.loads(
            await IntentListDueTool(tmp_path).execute(
                window_start="2026-03-27T00:00:00Z",
                window_end="2026-03-29T00:00:00Z",
            )
        )
        assert r["count"] == 1
        assert r["intents"][0]["title"] == "In window"

    async def test_overdue_included_by_default(self, tmp_path):
        await self._create(
            tmp_path, type="task", title="Overdue", due_at="2026-03-01T12:00:00Z"
        )
        r = json.loads(
            await IntentListDueTool(tmp_path).execute(
                window_start="2026-03-27T00:00:00Z",
                window_end="2026-03-29T00:00:00Z",
            )
        )
        assert r["count"] == 1

    async def test_overdue_excluded(self, tmp_path):
        await self._create(
            tmp_path, type="task", title="Overdue", due_at="2026-03-01T12:00:00Z"
        )
        r = json.loads(
            await IntentListDueTool(tmp_path).execute(
                window_start="2026-03-27T00:00:00Z",
                window_end="2026-03-29T00:00:00Z",
                include_overdue=False,
            )
        )
        assert r["count"] == 0

    async def test_done_excluded(self, tmp_path):
        cr = await self._create(
            tmp_path, type="task", title="Done", due_at="2026-03-28T12:00:00Z"
        )
        await IntentCompleteTool(tmp_path).execute(id=cr["intent"]["id"])
        r = json.loads(
            await IntentListDueTool(tmp_path).execute(
                window_start="2026-03-27T00:00:00Z",
                window_end="2026-03-29T00:00:00Z",
            )
        )
        assert r["count"] == 0

    async def test_snoozed_hidden_until_snooze_expires(self, tmp_path):
        cr = await self._create(
            tmp_path, type="task", title="Snoozed", due_at="2026-03-28T12:00:00Z"
        )
        await IntentSnoozeTool(tmp_path).execute(
            id=cr["intent"]["id"], snooze_until="2026-03-30T00:00:00Z"
        )
        r = json.loads(
            await IntentListDueTool(tmp_path).execute(
                window_start="2026-03-27T00:00:00Z",
                window_end="2026-03-29T00:00:00Z",
            )
        )
        # Snoozed until Mar 30, window ends Mar 29 — should not appear
        assert r["count"] == 0

    async def test_events_spanning_window(self, tmp_path):
        await self._create(
            tmp_path,
            type="event",
            title="Multi-day",
            start_at="2026-03-26T00:00:00Z",
            end_at="2026-03-29T00:00:00Z",
        )
        r = json.loads(
            await IntentListDueTool(tmp_path).execute(
                window_start="2026-03-27T00:00:00Z",
                window_end="2026-03-28T00:00:00Z",
            )
        )
        assert r["count"] == 1
        assert r["intents"][0]["title"] == "Multi-day"


# ---------------------------------------------------------------------------
# intent_sync_links
# ---------------------------------------------------------------------------


class TestIntentSyncLinks:
    async def test_rename_path(self, tmp_path):
        old = _make_entity_file(
            tmp_path, "memory/areas/people/old.md", "person_x", "person"
        )
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(
                type="task",
                title="Linked",
                links=[{"entity_path": "memory/areas/people/old.md"}],
            )
        )
        iid = r["intent"]["id"]

        # Simulate file rename
        new_path = tmp_path / "memory" / "areas" / "people" / "new.md"
        old.rename(new_path)

        r2 = json.loads(
            await IntentSyncLinksTool(tmp_path).execute(
                old_path="memory/areas/people/old.md",
                new_path="memory/areas/people/new.md",
            )
        )
        assert r2["updated"] >= 1

        # Verify the link was updated
        r3 = json.loads(await IntentGetTool(tmp_path).execute(id=iid))
        assert r3["intent"]["links"][0]["entity_path"] == "memory/areas/people/new.md"

    async def test_refresh_all(self, tmp_path):
        _make_entity_file(
            tmp_path, "memory/areas/people/p1.md", "person_p1", "person"
        )
        await IntentCreateTool(tmp_path).execute(
            type="task",
            title="T1",
            links=[{"entity_path": "memory/areas/people/p1.md"}],
        )
        r = json.loads(
            await IntentSyncLinksTool(tmp_path).execute(refresh_all=True)
        )
        assert r["updated"] >= 1

    async def test_sync_by_entity_id(self, tmp_path):
        _make_entity_file(
            tmp_path, "memory/areas/people/eid.md", "person_eid", "person"
        )
        await IntentCreateTool(tmp_path).execute(
            type="task",
            title="EID linked",
            links=[{"entity_path": "memory/areas/people/eid.md"}],
        )
        r = json.loads(
            await IntentSyncLinksTool(tmp_path).execute(entity_id="person_eid")
        )
        assert r["updated"] >= 1


# ---------------------------------------------------------------------------
# Backlink auto-management
# ---------------------------------------------------------------------------


class TestBacklinks:
    async def test_backlinks_cleared_when_no_active_intents(self, tmp_path):
        entity = _make_entity_file(
            tmp_path, "memory/areas/people/f.md", "person_f", "person"
        )
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(
                type="task",
                title="Temp",
                links=[{"entity_path": "memory/areas/people/f.md"}],
            )
        )
        assert "INTENTS:AUTO" in entity.read_text()

        # Cancel the intent
        await IntentUpdateTool(tmp_path).execute(
            id=r["intent"]["id"], status="canceled"
        )
        # Force backlink refresh
        await IntentSyncLinksTool(tmp_path).execute(entity_id="person_f")
        # Backlinks section should be gone
        content = entity.read_text()
        assert "INTENTS:AUTO" not in content

    async def test_backlinks_updated_on_link_replacement(self, tmp_path):
        e1 = _make_entity_file(
            tmp_path, "memory/areas/people/g1.md", "person_g1", "person"
        )
        e2 = _make_entity_file(
            tmp_path, "memory/areas/people/g2.md", "person_g2", "person"
        )
        r = json.loads(
            await IntentCreateTool(tmp_path).execute(
                type="task",
                title="Move link",
                links=[{"entity_path": "memory/areas/people/g1.md"}],
            )
        )
        assert "Move link" in e1.read_text()

        # Replace link from g1 to g2
        await IntentUpdateTool(tmp_path).execute(
            id=r["intent"]["id"],
            links=[{"entity_path": "memory/areas/people/g2.md"}],
        )
        # g1 should no longer have the backlink, g2 should
        assert "Move link" not in e1.read_text()
        assert "Move link" in e2.read_text()


# ---------------------------------------------------------------------------
# Tool schema compliance
# ---------------------------------------------------------------------------


class TestToolSchemas:
    """Verify all tools have valid schemas for the ToolRegistry."""

    @pytest.fixture(params=[
        IntentCreateTool,
        IntentUpdateTool,
        IntentGetTool,
        IntentSearchTool,
        IntentCompleteTool,
        IntentSnoozeTool,
        IntentDeferTool,
        IntentListDueTool,
        IntentSyncLinksTool,
    ])
    def tool(self, request, tmp_path):
        return request.param(tmp_path)

    def test_has_name(self, tool):
        assert tool.name.startswith("intent_")

    def test_has_description(self, tool):
        assert len(tool.description) > 10

    def test_parameters_is_object_schema(self, tool):
        params = tool.parameters
        assert params["type"] == "object"
        assert "properties" in params

    def test_to_schema_format(self, tool):
        schema = tool.to_schema()
        assert schema["type"] == "function"
        assert "function" in schema
        assert schema["function"]["name"] == tool.name
