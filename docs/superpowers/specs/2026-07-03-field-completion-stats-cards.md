# Field Completion Stats Cards

Date: 2026-07-03. Scope: 3 components, CSS, no backend changes.

## New: `FieldCompletionStatsCards.tsx`

Reusable component for field completion progress/results display, used by all three parent pages.

Props:
- `detail: FieldCompletionRunDetail | null` — run data from polling
- `status: string` — pending/running/succeeded/partially_succeeded/failed/cancelled
- `targetCount: number` — number of targets being completed
- `elapsedSec: number` — elapsed seconds
- `onCancel?: () => void` — cancel button handler
- `onClose: () => void` — close/dismiss handler

Modes: "progress" (running/pending) and "result" (terminal status).

### Progress mode (running/pending)
- Header: status text + elapsed time
- Progress bar: animated gradient, percentage based on item_count / estimated_total
- Two-column stat cards: left = execution overview (total fields, processed, model calls), right = completion results (updated, suggested, skipped, failed)
- Usage row: elapsed, avg per field, estimated remaining, token counts, cost estimate
- Footer: cancel + close buttons

### Result mode (terminal)
- Status banner: colored based on status (green=succeeded, yellow=partial, red=failed)
- Two-column stat cards: final numbers
- Items table: field_name, update_status badge, new value preview

## Modified: 3 parent components

Replace inline progress bars and ad-hoc result displays with `<FieldCompletionStatsCards>`.

## CSS

New classes: `.dc-fc-stats-*` prefixed, with medical-blue theme colors matching ExtractionProgressPanel style.
