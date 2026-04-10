---
name: memory
description: Multi-layer memory system with entity files, daily logs, and change ledger.
always: true
---

# Memory

## Structure

The memory system has 4 layers:

1. **Entity files** (`memory/areas/**/*.md`) -- Structured state + knowledge about people, places, projects, domains, resources, and systems
2. **Daily logs** (`memory/YYYY-MM-DD.md`) -- Raw chronological notes per day (one file per day, `### HH:MM` sections)
3. **Change ledger** (`memory/_index/changes.jsonl`) -- Structured append-only log of all entity creates/updates
4. **Cards index** (`memory/_index/_cards.md`) -- Auto-generated index of all entity CARD headers for LLM-based retrieval routing

### Long-term Memory
- `memory/MEMORY.md` -- Long-term facts (preferences, project context, relationships). Always loaded into your context.

### Entity Categories
Entity files live under `memory/areas/` in these subdirectories:
- `people/` -- People you interact with
- `places/` -- Locations and venues
- `projects/` -- Projects and initiatives
- `domains/` -- Knowledge domains, topics, skills
- `resources/` -- Books, articles, tools, references
- `systems/` -- Software systems, infrastructure, services

All entity files MUST follow `ENTITY_TEMPLATE.md` in the workspace root.

## Retrieving Past Events

To recall what happened on a specific date, read the daily file directly:
- `read_file memory/2025-03-26.md`

To find which dates have history, list the memory directory:
- `list_dir memory/` -- look for date-named `.md` files

To search across multiple days for a keyword, use `exec`:
- `grep -rl "keyword" memory/20*.md`
- Then read the matching files

## Retrieving Entity Knowledge

- Use `retrieve_entities` for fuzzy/semantic queries across entities (read the `entity-retrieval` skill for details)
- Use `grep -r` across `memory/areas/` for keyword-based search when you know what you're looking for
- Use `query_changes` for "what changed since/between/on" questions (read the `index-ledger-read` skill)

## When to Update MEMORY.md

Write important facts immediately using `edit_file` or `write_file`:
- User preferences ("I prefer dark mode")
- Project context ("The API uses OAuth2")
- Relationships ("Alice is the project lead")

## When to Create/Update Entity Files

On every interaction containing **durable signal**, create or update entity files under `memory/areas/**`:
- Decisions and commitments
- Status or role changes
- Milestones and progress updates
- Stable relationships or constraints
- Recurring patterns
- Biographical info about the primary user
- Learning notes and accumulated knowledge

After any entity create/update, use `record_change` to log it to the change ledger, then run `bash scripts/generate-cards-index.sh` to refresh the cards index.

## Auto-consolidation

Old conversations are automatically summarized into daily history files when the session grows large. Long-term facts are extracted to MEMORY.md. You don't need to manage this.
