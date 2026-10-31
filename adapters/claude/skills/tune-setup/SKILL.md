---
name: tune-setup
description: Re-tune the criteria of coach, the context notice, ticket-flow and grillme from the user's own /insights data, proposing a diff and editing only after approval. Use for "tune-setup", "re-tune the setup", "ajusta el coach con mis datos", "actualiza los criterios", "revisa mi uso", or when the SessionStart notice says tuning is due.
---

# Tune the setup from real usage

Goal: criteria that follow how the user really works. Propose, never apply on your own.

1. **Data.** Run `python3 -I adapters/claude/tune_stats.py` from the ai-setup repo. If it says no sessions, or the newest `~/.claude/usage-data/report-*.html` is older than the notice reason, ask the user to run `/insights` first and wait.
2. **Read the table, not the story.** A group marked `few data` is not evidence: say "few data" and propose nothing for it.
3. **Propose** one small change per piece, each with the number that supports it:
   - `coach` (`core/skills/coach/SKILL.md`, step 2): which task types need a stronger model or more effort, and which are over-served.
   - context notice (`adapters/claude/hooks/context_notice.py`, defaults 150k / 50k): move START/STEP only if friction jumps in the longer-session bucket.
   - `ticket-flow` (`core/skills/ticket-flow/SKILL.md`): the 2-round fix limit and the model per stage, only if Agent sessions show a real gap.
   - `grillme` (`core/skills/grillme/SKILL.md`): when to suggest it. If `wrong_approach` and `misunderstood_request` lead the friction, make the trigger earlier.
4. **Gate.** Show the diff as a table (piece · today · proposed · evidence) and wait for approval. Then edit, run `python3 -m unittest discover -s tests`, update the cheatsheet piece (`grep -n`, never read it whole), and stop before commit: the user commits.

Out of scope: guard/policy, other skills, anything outside these four pieces.
