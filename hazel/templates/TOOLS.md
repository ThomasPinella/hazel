# Tool Usage Notes

Tool signatures are provided automatically via function calling.
This file documents non-obvious constraints and usage patterns.

## exec — Safety Limits

- Commands have a configurable timeout (default 60s)
- Dangerous commands are blocked (rm -rf, format, dd, shutdown, etc.)
- Output is truncated at 10,000 characters
- `restrictToWorkspace` config can limit file access to the workspace

## cron — Scheduled Jobs

- Refer to the cron skill for usage.
- **Do not use cron for reminders** — use the intents system instead.

## intent_create — Create Intent

- Creates a task, reminder, event, or followup in `data/intents.db`
- Types: `task`, `reminder`, `event`, `followup`
- All timestamps must be UTC ISO8601 ending in Z
- Use `links` to associate with entity files (entity_path and/or entity_id)
- Returns a ULID-based ID

## intent_update — Update Intent

- Partial update of any fields on an existing intent
- Passing `links` replaces all existing links
- Status changes automatically refresh entity backlinks

## intent_get — Get Intent

- Fetch a single intent by ULID, including its linked entities

## intent_search — Search Intents

- Full-text search on title/body
- Filters: `status`, `type`, `due_start`/`due_end`, `entity_path`, `entity_id`
- Supports `limit` and `offset` for pagination

## intent_complete — Complete Intent

- Marks a non-recurring intent as `done`
- For recurring intents (with `rrule` + `due_at`), advances to next occurrence instead

## intent_snooze — Snooze Intent

- Sets `snooze_until` timestamp and status to `snoozed`
- Snoozed intents are hidden from `intent_list_due` until snooze expires

## intent_defer — Defer Intent

- Clears `due_at`, increments `deferrals` counter, resets status to `active`
- Use when the user wants you to pick the next time

## intent_list_due — Agenda Query

- Returns intents due within a time window
- Supports `include_overdue` to include past-due items
- Excludes done/canceled; respects snooze

## intent_sync_links — Sync Entity Links

- Handles entity path renames: `old_path` -> `new_path`
- Can refresh by `entity_id` or do a full `refresh_all`
- Call after renaming/moving entity files
