---
name: user-preferences
description: User communication language, workflow preferences, and constraints
metadata:
  type: user
---

# User Preferences

## Language
- Chinese-speaking. Communicate in Chinese.
- UI text should be Chinese (医学蓝配色, Chinese neuroanatomy terminology).

## Workflow Style
- Prefers organic integration — features should blend into existing UI, not add separate pages.
- Prefers "subagent-driven development" (`/subagent-driven-development`) for multi-task implementation.
- Uses brainstorming → writing-plans → subagent-driven-development pipeline.

## Technical Constraints
- "不要改后端" / "只修前端" — frequently wants frontend-only fixes.
- LLM extraction prompt: Mirror KG is candidate layer, bias toward recall.
- All LLM output goes to mirror_*, NEVER final_*.
- No auto-approve, no auto-promote.
- Backend tests must pass (1065+ baseline). Frontend `npm run build` must have 0 errors.
- Pool is auto-created by (source_atlas, granularity_level, granularity_family) scope.

## Known Stance
- Wants many connections (2000+ target). Dislikes conservative prompts that suppress candidates.
- Prefers exact data — 300+ connections is "too few".
- Pool should "just work" — auto-accumulate, no manual pool creation required.
- Modal UI should be consistent size across states.
- Log console should not block data — dynamic height, not fixed.

**Why:** Guides all design and implementation decisions.
**How to apply:** Check before proposing any new feature or fix.
