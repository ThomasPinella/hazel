---
name: entity-retrieval
description: Find relevant memory entities using LLM-based CARD routing. Use for questions requiring knowledge from memory/areas/**. Returns paths for you to unfold.
---

# Entity Retrieval Skill

Use this skill when answering questions that require knowledge from the memory system,
especially for:
- Fuzzy/semantic queries ("what do I know about X?")
- Cross-domain questions ("what connects A to B?")
- Questions where you don't know which entities are relevant

## When to Use

**Use `retrieve_entities` when:**
- Question requires searching across unknown entities
- Query is semantic/fuzzy (not asking for a specific known file)
- Cross-domain synthesis is needed
- You need to discover relevant context

**Don't use when:**
- You already know the exact entity (just read it directly)
- Question is time-based ("what changed today?") -> use `query_changes` instead
- You're following explicit CARD links -> traverse directly

## Procedure

1. **Formulate query** -- Capture the user's intent. Include key concepts, domains, and what kind of information would help.

2. **Call `retrieve_entities`:**
   ```
   retrieve_entities(
     query: "the user's question or topic",
     count: 10,
     context: "optional recent conversation context"
   )
   ```

3. **Unfold returned paths** -- For each relevant path returned, read the file using `read_file`:
   - Start with top 3-5 most relevant
   - Unfold more if needed for synthesis
   - Cap at ~10 full reads to avoid context bloat

4. **Check CARD links** -- If unfolded entities have `links` in their CARD, consider following 1-2 linked entities for additional context.

5. **Synthesize** -- Combine insights across entities to answer the question. Cite sources.

## Query Formulation Tips

- Include the domain/topic: "gym routine, AI, basketball"
- Include the intent: "what connects X to Y"
- Include relevant context: "personal patterns with dating"
- Avoid single words or overly long queries (keep under ~50 words)

## Budgets

- Default `count`: 10 paths
- Recommended unfolds: 3-5 entities (expand if needed)
- Max unfolds per query: 10 (avoid context bloat)
