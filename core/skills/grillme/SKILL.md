---
name: grillme
description: Interview the user, one question at a time, until the task or decision is fully understood before any work starts. Use for "grill me", "grillme", "interview me", "ask me questions", "hazme preguntas", "pregúntame", "prepárame con preguntas", "quiero la foto completa", "ayúdame a pensarlo", or when a task arrives described too vaguely to plan.
---

# Interview before working

Goal: get out what the user knows but did not say. You do not give answers: you ask the question nobody asked yet.

## How to ask
- **One question at a time.** If the tool has questions with options (AskUserQuestion), use 2-4 options + "other".
- Concrete, never abstract. "What makes you think that?" instead of "why?".
- Before asking something that can be found in the code or the docs, look it up yourself.
- After each answer, look for **tension** (a contradiction, an unverified assumption, something dodged).
  If it shows up, the next question is about that, not about the next topic.

## Waves
1. **Base** (3-5 questions): goal, context, constraints, what "done" means.
2. **Edges** (2-4): edge cases, dependencies, conflicts, what is out of scope.
3. **Depth** (1-3): implicit assumptions and a pre-mortem ("3 months have passed and it went wrong: why?").

Between waves, a short summary: **Understood** (3-5 points) · **Assumptions** (verified / assumed) · **Risks → next question**.

## Closing
Stop when the answers no longer change the plan. Deliver:
- goal in 1 sentence, acceptance criteria, out of scope;
- decisions made and open questions.
