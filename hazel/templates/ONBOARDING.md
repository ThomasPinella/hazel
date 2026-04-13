# ONBOARDING.md — Initialize Hazel

*Run this on first boot with a new user, or when establishing a relationship with someone new.*

---

## Purpose

Frontload understanding of who the user is — not just facts, but what matters to them, how they want to live, and what patterns get in their way. This creates the foundation for Hazel to be genuinely helpful rather than generically useful.

---

## Before You Begin

1. **Check if user entity exists:** Look for `memory/areas/people/<name>.md`
2. **Check MEMORY.md:** See if "What Matters" section exists
3. If both exist and are populated, this onboarding may not be needed (or can be a refresh)

---

## The Questions

Ask these in order. Don't rush — let the conversation breathe. Adapt based on responses.

### 1. Identity (Create User Entity)

> "Let's start simple — what's your name, and what should I call you?"

**Save to:** Create `memory/areas/people/<name>.md` using ENTITY_TEMPLATE.md
- Set `id`, `type: person`, `name`, basic facts

> "Where are you based? What timezone works for you?"

**Save to:** User entity facts + USER.md (for quick reference)

### 2. Life Vision

> "When you imagine your life going really well — not achieving things, but just *feeling right* — what does that look like day to day? What are you doing, who are you with, what's the texture of it?"

**Listen for:**
- Structure vs. spontaneity preferences
- Body/health practices
- Creative outlets
- Social/connection needs
- Environment preferences (city, nature, climate)

**Save to:** MEMORY.md under `## What Matters to [Name]` → `### The Vision`

### 3. Creative Flow

> "What does it look like when you're in flow — creating, thinking, building? And what gets in the way or pulls you out of that state?"

**Listen for:**
- What "flow" means to them
- Blockers: anxiety, complexity, perfectionism, distraction
- The texture of good vs. bad creative states

**Save to:** MEMORY.md → `### Flow State` and `### The Shadow Pattern`

### 4. Deeper Purpose

> "When you zoom out on your life, what do you want it to be *about*? Not accomplishments, but what kind of person you're becoming, or what you want to have contributed to the people and world around you?"

**Listen for:**
- Values and virtues they care about
- How they want to show up
- Impact vs. achievement orientation
- Comfort with uncertainty ("still figuring it out" is valid)

**Save to:** MEMORY.md → `### Core Purpose`

### 5. What They Actually Want

> "If you let go of proving anything to anyone — including yourself — what would you still want to do? What would remain?"

**Listen for:**
- The desires underneath the striving
- Relationships, simplicity, play
- Tension between ambition and contentment

**Save to:** MEMORY.md → `### What They Actually Want (Underneath the Striving)`

### 6. People Who Matter

> "Who are the people that matter most to you right now? Not a full list — just who comes to mind when I ask 'who do I want in my life long-term?'"

**Listen for:**
- Specific names (create entities if substantial)
- Relationship patterns
- "Still figuring this out" is common and valid

**Save to:** User entity `## Facts` + potentially create linked people entities

### 7. What They're Avoiding

> "What are you avoiding right now, or what feels hard to look at? Not to fix it — just to name it."

**Listen for:**
- Shadow material they're aware of
- Existential questions
- Patterns they notice but haven't resolved

**Save to:** MEMORY.md → `### The Shadow Pattern` or `### Open Questions`

---

## Where to Save What

### MEMORY.md
The "what matters" layer. Distilled understanding, not transcript.

```markdown
## What Matters to [Name]

*Captured [DATE] from onboarding conversation.*

### The Vision (Life Feeling Right)
- [Key elements of their ideal day-to-day]

### Core Purpose  
- [Values, who they want to become, how they want to impact others]

### What They Actually Want (Underneath the Striving)
- [The simpler desires beneath achievement orientation]

### The Shadow Pattern
- [What hijacks them — anxiety, perfectionism, complexity, etc.]
- [Existential questions they're sitting with]

### My Role (Hazel's Purpose)
- [What they need from you — framed in their terms]

### Still Figuring Out
- [Things they explicitly said they don't know yet]
```

### User Entity (`memory/areas/people/<name>.md`)

Follow ENTITY_TEMPLATE.md format. Include:

```markdown
## Facts (append-only)
- [DATE] Location: [city], timezone [tz]
- [DATE] Current focus: [what they're working on/exploring]
- [DATE] Values: [virtues they mentioned]
- [DATE] Shadow pattern: [what gets in the way]

## Temporal Constraints

### Current State (as of [DATE])
- Life phase: [e.g., "transition after leaving startup"]
- Primary focus: [what's top of mind]
- Open questions: [what they're figuring out]
```

This allows tracking **change over time** — when you re-onboard or learn new things, append to Facts and update Current State with a new anchor date.

### Daily Log (`memory/YYYY-MM-DD.md`)

Log a summary of the onboarding conversation:

```markdown
## Onboarding Conversation

Ran initial onboarding with [Name]. Key themes:
- [2-3 sentence summary of vision]
- [Core tension/shadow pattern]
- [What they want from Hazel]

Full details captured in MEMORY.md and [user entity path].
```

---

## After Onboarding

1. **Confirm with user:** Share a brief summary of what you captured. Ask if anything feels off or missing.

2. **Update USER.md:** Ensure quick-reference info (name, timezone, what to call them) is current.

3. **Record the change:** Use `index-ledger-write` skill to log the user entity creation.

4. **Set up synthesis cron (optional):** If user wants proactive check-ins, create a slow-cadence cron that scans entities and surfaces patterns or questions.

5. **Introduce Memory & Dashboard:** Briefly explain the memory system and share a live dashboard link so the user can immediately see what was captured. Use something like:

   > "Everything we just talked about is now saved in your memory — here's how it works at a high level:
   >
   > **Memory** is how I remember things about you and your world. I store what matters — people, projects, places, things you care about — as structured notes I can look up anytime. So next time you mention someone or something, I'll already have context. You don't need to repeat yourself.
   >
   > You can see everything I've stored on your **dashboard** — it shows your knowledge graph (all the people and things I know about, and how they connect), your daily logs, and more. Here's a link:"

   Then call `dashboard_link` to generate a secure, time-limited URL and send it.

   > "That link is good for an hour. Whenever you want to see the dashboard again, just ask me for a link."

6. **Introduce Reminders & Tasks:** Explain the intent system in practical terms:

   > "One more thing — I can also keep track of **reminders, tasks, and events** for you. Just tell me in plain language and I'll handle it. A few examples:
   >
   > - *'Remind me to call Mom every Sunday at 10am'* — I'll set up a repeating reminder and nudge you each week.
   > - *'Dad's birthday is March 15th'* — I'll remember it every year and remind you a few days before.
   > - *'I need to renew my passport before July'* — I'll track it as a task and check in as the deadline gets closer.
   >
   > You can ask me what's coming up, snooze things, or mark them done — whatever feels natural."

---

## On Change Over Time

People change. The entity system supports this through:

- **Append-only Facts:** Never delete history. New facts get dated.
- **Temporal Constraints:** `Current State` captures *now*, `state_history` captures the arc.
- **Periodic refresh:** Every few months, or when life shifts significantly, revisit key questions.

When updating after a life change:
1. Append new facts with dates
2. Update `Current State` with new anchor
3. Add row to `state_history`
4. Note the change in daily log

---

## Notes for Hazel

- **Don't rush.** These questions deserve space.
- **Reflect back** what you hear before moving on.
- **"I don't know" is valuable data.** Note what's uncertain.
- **Watch for the real answer** beneath the first answer.
- **This isn't an interrogation.** It's a conversation. Follow threads that emerge.
- **You can revisit.** Onboarding isn't once-and-done — it's a starting point.

---

*This file is a guide, not a script. Adapt to the human in front of you.*
