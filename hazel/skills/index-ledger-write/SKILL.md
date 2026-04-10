---
name: index-ledger-write
description: Record one deterministic changelog entry after creating/updating an entity file in memory/areas/**. Use immediately after an intentional CREATE or UPDATE.
---

# Index Ledger Write

Use this skill immediately after an intentional CREATE or UPDATE of an entity file under `memory/areas/**`.

## Tool: record_change

Appends one structured row to `memory/_index/changes.jsonl`.

### Required Parameters

- **op**: `create` | `update`
- **path**: Path to the entity file (e.g. `memory/areas/projects/example.md`)
- **reason**: `runtime` | `daily_compress` | `manual` | `import`

### Optional Parameters

- **source**: Source pointer (e.g. `memory/2026-01-27.md`)
- **summary**: One-line description of what changed
- **entity_id**: Parsed from CARD header if omitted
- **entity_type**: `person` | `place` | `project` | `domain` | `resource` | `system` -- parsed from CARD if omitted
- **tags**: String array -- parsed from CARD if omitted
- **dedupe_seconds**: 0-60, default 5 -- dedupes identical writes within this window

### Behavior

1. Timestamp (`ts`) is auto-generated (UTC ISO-8601).
2. If `entity_id`, `entity_type`, or `tags` are omitted, the tool reads them from the file's `<!-- CARD ... -->` header.
3. Built-in 5s dedupe prevents duplicate entries for rapid successive writes to the same file.

## Steps

1. Call `record_change` with at minimum: `op`, `path`, `reason`.
2. Include `summary` when the change is meaningful.
3. **Regenerate the cards index** after recording:
   ```bash
   bash scripts/generate-cards-index.sh
   ```
   This keeps `memory/_index/_cards.md` fresh for retrieval.
4. One ledger entry per logical change -- the dedupe window handles accidental duplicates.
