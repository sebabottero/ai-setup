---
name: session-handoff
description: Write a self-contained handoff prompt so another agent session (another Orca workspace, another tool, or a fresh session) can continue or fix work without this conversation. Use for "write the prompt for the other session", "hand this to the other session", "genera el prompt para la otra sesión", "pásale esto a la otra sesión", "cómo le aviso de los cambios", or before ending a long session.
---

# Handoff prompt between sessions

Save the prompt in a file outside the repo (by default `~/handoffs/<ticket>-<topic>.md`) and give the user the path.
The other session cannot see this conversation: everything it needs goes in the file.

## Template
```markdown
# Handoff: <ticket> — <topic>

## Goal
<what the other session has to achieve, in 1-2 sentences>

## Minimal context
- Repo and branch: <path> · <branch> (base: <base>)
- Ticket: <URL>. Related PRs: <URLs and status>
- Decisions already made: <short list, with who made them>

## What is done
- <point> (commit/PR)

## What has to be done
1. <concrete, verifiable step>

## Out of scope
- <what it must NOT touch>

## Rules
- Only one session writes on this branch: <which>.
- Commit and push only with the user's OK.
- Be skeptical of these proposals: if something makes no sense once you see the code, say so before applying it.

## How to verify
- <checks to run; use the validate skill or the leaf-verify agent>

## Expected delivery
Receipt: what changed · what ran · what happened · what failed · what is uncertain.
```

Before handing it over, check that it makes sense without having read this conversation.
