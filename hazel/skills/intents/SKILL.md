---
name: intents
description: >
  Manage intents: tasks, reminders, events, and followups stored in a local SQLite database
  with bidirectional entity linking. USE THIS SKILL when:
  - User asks to set a reminder ("remind me", "don't let me forget", "ping me about")
  - User asks to create a task ("add a task", "I need to", "todo", "put on my list")
  - User asks to schedule an event ("set up a meeting", "block time for", "schedule")
  - User asks to create a followup ("follow up with", "check back on", "circle back")
  - User asks about their agenda ("what's due", "what do I have today", "my tasks", "agenda")
  - User asks to snooze, defer, reschedule, or cancel an intent
  - User asks to complete/finish/check off a task or reminder
  - User asks to search intents ("find that task about", "do I have a reminder for")
  - You are creating any time-based notification for the user
  - You need to link an intent to an entity or check entity-linked intents
  DO NOT use this skill when:
  - Setting up recurring infrastructure cron jobs (use cron tool directly)
  - The user is just talking about plans casually without wanting them tracked
  - Reading/writing entity files that happen to have a Linked Intents section (that's auto-managed)
---

# Intents — Tasks, Reminders, Events, Followups

## Tools

| Tool | Purpose |
|------|---------|
| `intent_create` | Create a new task/reminder/event/followup with optional entity links |
| `intent_update` | Update any fields on an existing intent (partial update) |
| `intent_get` | Get a single intent by ID with its links |
| `intent_search` | Search with filters (text, status, type, time windows, entity_id/path) |
| `intent_complete` | Mark done (or advance recurring to next occurrence) |
| `intent_snooze` | Snooze until a specific time |
| `intent_defer` | Clear due_at, increment deferrals counter (user defers timing to you) |
| `intent_list_due` | Agenda query for time windows |
| `intent_sync_links` | Sync links after entity path changes |

## Types & Status

**Types:** `task` | `reminder` | `event` | `followup`

**Status:** `active` | `done` | `canceled` | `snoozed`

## Fields

### Time (all UTC ISO8601 ending in Z)
- `due_at` — when it's due (tasks, reminders, followups)
- `start_at` / `end_at` — event time range
- `snooze_until` — when snoozed intent resurfaces
- `timezone` — IANA timezone for display only (e.g., "America/Los_Angeles")
- `last_fired_at` — last notification sent (used by notification cron)

### Other
- `priority` — 0-3, default 1
- `estimate_minutes` — optional time estimate
- `body` — optional notes/description
- `rrule` — RFC 5545 RRULE string for recurrence (e.g., "FREQ=WEEKLY;BYDAY=MO")
- `deferrals` — counter incremented each time user defers timing back to you
- `rescheduled_count` — counter for manual reschedules
- `location_text` — location for events
- `attendees_json` — JSON string of attendees for events

---

## CRITICAL: Reminders Use Intents, NOT Cron

**DO NOT create one-shot cron jobs for reminders, tasks, or events.**

A notification cron already runs every 5 minutes and handles all time-based notifications. Your job is to create the intent — the cron handles delivery.

**For ANY user request involving time-based notifications:**
1. Use `intent_create` with the appropriate `type`
2. Set `due_at` to a UTC ISO8601 timestamp
3. Link relevant entities (see below)
4. Done. The notification cron picks it up.

**Examples:**
- "Remind me in 20 minutes" -> `intent_create(type="reminder", title="...", due_at="<now+20min UTC>")`
- "Add a task due Friday" -> `intent_create(type="task", title="...", due_at="<Friday UTC>")`
- "Set an event for 3pm" -> `intent_create(type="event", title="...", start_at="<3pm UTC>", end_at="<4pm UTC>")`

**Why intents, not cron:**
- Intents are tracked, searchable, and linkable to entities
- One-shot cron jobs are fire-and-forget with no history
- The notification cron already exists — don't duplicate infrastructure

---

## Creating Intents

### Step 1: Identify & Link Entities

Before calling `intent_create`, find entities referenced in the request:
- People, projects, topics, companies, systems
- Search for matching entity files if unsure which exist
- Include in `links` parameter

**Example:** "Remind me to follow up with Emmanuel about the retreat platform"
```
intent_create(
  type: "followup",
  title: "Follow up with Emmanuel about retreat platform",
  due_at: "2026-02-05T17:00:00Z",
  links: [
    { entity_path: "memory/areas/people/emmanuel.md" },
    { entity_path: "memory/areas/projects/retreat-platform.md" }
  ]
)
```

### Step 2: Bootstrap New Entities If Needed

If an intent references a person/company/place that doesn't have an entity file yet, create one **before** the intent if:
- It's specific and identifiable (not "the plumber")
- You have at least one durable fact beyond the name
- It's likely to be referenced again

**Do it:** "Meeting with Sarah Chen from Anthropic" -> create `memory/areas/people/sarah-chen.md` first
**Don't:** "Call the dentist" -> too generic

Create entities first -> then `intent_create` with links in a single call.

### Step 3: Intelligent Timing (No Due Date Given)

When the user doesn't specify a time:

1. **Gather context:**
   - `intent_search(entity_id=..., status=["active", "snoozed"])` — related intents
   - `intent_list_due` for next ~2 weeks — current workload
   - Check calendar if available
2. **Pick a reasonable `due_at`** based on:
   - Urgency signals ("soon", "eventually", "when you get a chance")
   - Avoid conflicts with existing intents and calendar
   - Balance workload across days
   - Respect working hours
3. **Add timing rationale to `body`** — e.g., "Scheduled for Monday morning — calendar is light then."

---

## Managing Intents

### Complete
```
intent_complete(id: "01KGBSRV...")
```
- Non-recurring: marks as `done`
- Recurring (has `rrule`): advances `due_at` to next occurrence, stays `active`

### Snooze
```
intent_snooze(id: "01KGBSRV...", snooze_until: "2026-02-05T09:00:00Z")
```

### Defer (user says "you pick the time")
```
intent_defer(id: "01KGBSRV...")
```
- Clears `due_at`, increments `deferrals`, sets status to `active`
- You pick a new time on next interaction
- Multiple deferrals may signal lower priority — consider asking about it

### Reschedule (user picks new time)
```
intent_update(id: "01KGBSRV...", due_at: "2026-02-07T15:00:00Z", rescheduled_count: <current + 1>)
```

### Cancel
```
intent_update(id: "01KGBSRV...", status: "canceled")
```
Never delete — canceled preserves audit trail.

---

## Querying

### Today's agenda
```
intent_list_due(
  window_start: "2026-02-01T00:00:00Z",
  window_end: "2026-02-02T00:00:00Z"
)
```

### By entity
```
intent_search(entity_id: "project_hazel", status: ["active"])
```

### By text
```
intent_search(q: "documentation", status: ["active", "snoozed"])
```

---

## Bidirectional Links

- **Intent -> Entity**: `intent_links` table stores `entity_id` (stable key) + `entity_path`
- **Entity -> Intent**: Auto-managed `## Linked Intents` section in entity markdown
- Backlinks update automatically on status changes
- `entity_id` is the stable key — paths can change, IDs persist

### Path Changes
When entity files move:
```
intent_sync_links(old_path: "old/path.md", new_path: "new/path.md")
```
Periodic refresh:
```
intent_sync_links(refresh_all: true)
```

---

## Recurrence

- Set `rrule` to an RFC 5545 RRULE string: `"FREQ=DAILY;INTERVAL=1"`, `"FREQ=WEEKLY;BYDAY=MO"`
- `intent_complete` on a recurring intent advances `due_at` to next occurrence instead of marking done
- If no next occurrence (COUNT limit), marks as done normally

---

## Time Handling

- All times stored as **UTC ISO8601** ending in Z
- `timezone` field is for display only
- **Never manually calculate timestamps** — use shell:

```bash
# Relative time -> UTC
date -d "+20 minutes" -u +"%Y-%m-%dT%H:%M:%SZ"

# Specific time with timezone -> UTC
TZ=America/Los_Angeles date -d "2026-02-05 15:00" -u +"%Y-%m-%dT%H:%M:%SZ"

# Verify day-of-week before stating it
date -d "2026-02-05" +%A
```

---

## Design Principles

- **No delete** — only `status=canceled`
- **UTC storage** — timezone for display only
- **ULID IDs** — sortable, contains timestamp
- **entity_id as stable key** — paths can change
- **Bidirectional links** — DB -> entity file, entity file -> DB
- **Recurring in-place** — advance `due_at`, don't clone
- **Deferrals + reschedule counts** — help learn priority patterns
