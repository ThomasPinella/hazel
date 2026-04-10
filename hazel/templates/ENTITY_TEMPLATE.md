# ENTITY_TEMPLATE.md

Purpose:
Entity files in `memory/areas/**` are the durable, structured **state + knowledge** layer of the memory system.
They complement daily logs (`memory/YYYY-MM-DD.md`) by capturing:
- ongoing state (for people, projects, systems)
- accumulated understanding (for domains, places, skills, resources)

---

## Directory + filename conventions

- People:    memory/areas/people/<slug>.md
- Places:    memory/areas/places/<slug>.md
- Projects:  memory/areas/projects/<slug>.md
- Domains:   memory/areas/domains/<slug>.md
- Resources: memory/areas/resources/<slug>.md
- Systems:   memory/areas/systems/<slug>.md

---

## ID conventions

- person_<slug>
- place_<slug>
- project_<slug>
- system_<slug>
- domain_<slug>
- resource_<slug>

---

## Slug rules
- lowercase
- hyphen-separated
- stable over time (do not rename unless necessary)

---

## Required file structure (in this order)

1) CARD header (required)
2) Temporal Constraints section (required, but may be minimal)
3) Facts section (required)
4) Notes / Knowledge section (optional but recommended for domains)

---

## 1) CARD header (required)

Rules:
- CARD is routing + identity only. Do NOT put detailed facts or history here.
- Keep it small and stable.
- Make `gist` keyword-rich to help hybrid retrieval.
- `tags` should be short (5-12), stable, and lowercase.
- Tag with `temporal` if the entity has time-evolving state tracked in Temporal Constraints.
- `links` are optional, typed edges to other entities.
- For domains, `gist` should describe the **domain or subject**, not a momentary insight.

Template:

<!-- CARD
id: <type>_<slug>
type: <person|place|project|domain|resource|system>
gist: <1-2 sentences, keyword-rich, describing what this entity is and why it matters>
tags: ["tag1","tag2","tag3"]
aliases: ["Optional Alias 1","Optional Alias 2"]
links:
  - {rel: <relationship_type>, to: <other_entity_id>, notes: "<optional short note>"}
  - {rel: <relationship_type>, to: <other_entity_id>}
-->

Recommended relationship types (examples, not exhaustive):

- people: reports_to, manages, works_with, friend_of, family_of
- places: located_in, near, visited, lives_in, based_in
- projects: owned_by, used_by, depends_on, integrates_with, related
- systems: uses, powers, stores, integrates_with, depends_on
- domains: related, prerequisite_for, applied_to, contrasts_with, example_of
- resources: references, uses, created_by, recommended_by

---

## 2) Temporal Constraints (required)

Some entities have **time-evolving state** (people, projects, systems).
Some entities primarily accumulate **knowledge** (domains, places, resources).

Rules:
- This section is REQUIRED, but may be minimal for timeless or knowledge-centric entities.
- If "Current State" is present, it MUST include a temporal anchor: "as of YYYY-MM-DD" (preferred).
  - Use an ISO timestamp "YYYY-MM-DDTHH:MM:SSZ" only for fast-changing systems.
- State History is append-only.
- State History SHOULD exist, but MAY be empty if no state transitions have been recorded yet.
  - If included, each entry MUST use the same anchor format as Current State.
- If an entity is largely timeless, Current State may simply describe scope or coverage (still anchored).

Template:

## Temporal Constraints

### Current State (as of [anchor])
- <state bullet>
- <state bullet>

### State History
state_history:
  - when: "[anchor]"
    event: "[what happened]"
    new_state: "[resulting state]"

### Potential Triggers
- <trigger that would change state>
- <trigger that would change state>

Guidance:
- For **domains / knowledge entities**, Current State may reflect:
  - current level of understanding
  - scope covered so far
  - phase of learning (e.g. "introductory", "hands-on", "advanced")
- State History may be sparse or omitted if no meaningful transitions exist.
- Potential Triggers are optional for non-temporal domains.

---

## 3) Facts (append-only) (required)

Goal:
Durable, timestamped claims, observations, or conclusions.
Preserve history. Prefer superseding over deleting.

Rules:
- Append-only bullets
- Each fact starts with YYYY-MM-DD
- Include a source pointer when possible (daily log filename, trip date, book, etc.)
- If a fact is no longer true or superseded, do NOT delete it.

Template:

## Facts (append-only)
- YYYY-MM-DD: <durable fact or observation> (source: memory/YYYY-MM-DD.md)

What counts as a "durable fact":
- decisions and commitments
- role, relationship, or status changes
- project milestones and outcomes
- recurring patterns
- stable preferences or constraints
- learned conclusions or confirmed observations
- non-trivial insights that remain useful over time

What does NOT belong here:
- fleeting moods
- raw transcripts
- speculative ideas that never recur
- one-off plans that didn't happen

---

## 4) Notes / Knowledge (optional but recommended for domains)

Goal:
Capture accumulated understanding, observations, excerpts, and experiential notes.

Rules:
- Especially appropriate for `type: domain`.
- Can be longer-form with bullet lists, short paragraphs, or subheadings.
- May reference Facts but should not duplicate them verbatim.

## Notes
- <observation>
- <lesson learned>
- <interesting detail>
- <open question or area to explore>
