---
name: coach
description: Before a task, say in at most 5 lines which model and effort to use and how to phrase the prompt so it needs fewer back-and-forths. Use for "/coach", "coach", "qué modelo uso para esto", "cómo le pido esto", "which model should I use", "how should I phrase this", or before starting a task when unsure how to ask.
---

# Coach: before the task

Goal: fewer back-and-forths. Answer in **5 lines or less**, in the user's language. No theory, no survey.

1. **Classify** the task from what the user wrote (and the repo, if it is obvious): question, small edit, new feature, bug, big ticket, setup change.
2. **Model and effort** (cheapest that does the job dependably):
   - question, small edit, search, summary → fast model, low effort;
   - feature or refactor with a known plan → default model, medium effort;
   - hard bug diagnosis, architecture, ambiguous scope → strongest model, high effort, only for that step.
3. **Prompt**: rewrite the user's request with the four things that avoid rework: goal · success criteria · what is out of scope · files or commands to start from. Mark with `?` what is missing instead of inventing it.
4. **Process hint**, one line only if it applies: vague → `grillme`; big ticket → `ticket-flow`; bug → `systematic-debugging`; long unrelated context → `/clear` first.

Output format:

```
Tarea: <type>
Modelo: <model> · esfuerzo <level>  (why, 5 words)
Prompt: <improved request in 1-3 lines>
Falta: <missing items or "nada">
```

Do not start the task. Do not read files unless one is needed to classify. Wait for the user to send the prompt.
