---
name: index-ledger-read
description: Answer "what changed since/between/on" questions by querying the ledger deterministically, then loading entity files for context.
---

# Index Ledger Read

Use this skill for user questions like:
- "What changed since 2026-01-10?"
- "What changed between 2026-01-10 and 2026-01-20?"
- "What was updated on 2026-01-15?"

## Rules

- Do NOT search the JSONL changelog with grep for time-based queries.
- Always query via `query_changes` first.
- Then load the impacted entity files using `read_file` to provide real context.

## Procedure

1. Translate the user request into a `query_changes` call:
   - `since`: date/time lower bound (inclusive)
   - `until`: date/time upper bound (exclusive) if provided
   - Optional filters: `reason`, `op`, `entity_type`, `path_prefix="memory/areas/"`

2. Call `query_changes` and get rows.

3. Group rows by entity path (dedupe multiple entries for the same entity).

4. For each affected entity path (cap at 10 entities):
   - Read the start of the file (first ~220 lines) to capture CARD + Temporal Constraints + recent Facts.

5. Produce the answer:
   - Concise change summary list (grouped by entity).
   - Per-entity "what it means now" using the loaded Current State.
   - If more than 10 entities affected, summarize counts + offer to expand.
