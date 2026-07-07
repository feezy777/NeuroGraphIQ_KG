# Field Completion Step Wizard

Date: 2026-07-03. Rewrites FieldCompletionModal as 4-step wizard.

## Steps

1. **Select** — show selected objects + missing fields preview (informational, pre-filled from parent)
2. **Configure** — provider/model, field_scope, overwrite_policy, create_mirror_updates
3. **Dry Run** — auto-trigger dry run, show stats cards with estimated counts/tokens/cost
4. **Execute** — confirm → async execution → FieldCompletionStatsCards progress → result

## Navigation

- Step indicator at top: blue current, green completed, gray pending
- Footer: Cancel + Back/Next. Next label varies by step.
- Can go back any time (keeps state). Dry run must complete before execute.

## State

Single `step` state (0-3), reuses existing options/response/loading state.
On step 3 entry: auto-triggers dryRun API call.
On step 4 entry: auto-triggers execute API call with async polling.

## Files

- `FieldCompletionModal.tsx` — full rewrite
- `FieldCompletionStatsCards.tsx` — already done
- `styles.css` — step indicator styles
