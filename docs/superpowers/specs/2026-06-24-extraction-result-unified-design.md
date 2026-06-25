# Unified Extraction Result Display & Task Filter

**Date:** 2026-06-24 | **Status:** implementing

## Summary

Redesign LLM extraction result entries for ALL 12 extraction types with a unified hybrid (compact row → expandable card) component architecture, plus a two-level task type/run filter bar.

## Architecture

```
LlmExtractionPage.tsx (orchestration, slimmed down)
├── TaskFilterBar          ← new: two-level cascade filter + search
└── ExtractionResultPanel  ← new: unified result panel per type
    ├── ResultRow          ← new: compact row (default)
    │   └── ResultCard     ← new: expanded detail card
```

## Components

| Component | Responsibility |
|-----------|---------------|
| `TaskFilterBar` | Two dropdowns (task_type → run_id) + search input, emits filter events |
| `ExtractionResultPanel` | Receives type config + filter params, fetches data, renders result list |
| `ResultRow` | One summary row (icon, label, confidence, status), click to toggle expand |
| `ResultCard` | Expanded full detail fields + action buttons |

## Type-Driven Configuration

Each extraction type defines an `ExtractionTypeConfig`:
- `targetType` — which entity type
- `icon`, `labelField`, `statusField`, `confidenceField`
- `detailFields: DetailField[]` — which fields to show in expanded card
- `actions: ResultAction[]` — buttons (view detail, jump to Mirror, etc.)
- `fetchFn` — data fetching function

12 configs in `extractionTypeConfigs.ts`.

## Interaction

- **Compact row:** 48px, icon + label left, confidence badge + status badge right
- **Expand:** accordion (one at a time), 4-6 key fields + actions
- **Confidence color:** ≥0.8 green, 0.5-0.8 yellow, <0.5 red
- **Status badge:** reuse existing StatusBadge
- **Empty state:** per-type empty message
- **Loading:** skeleton screen (3 gray pulse rows)

## Files

| File | Action |
|------|--------|
| `llm-extraction/types/extractionConfig.ts` | New — type + 12 configs |
| `llm-extraction/components/TaskFilterBar.tsx` | New |
| `llm-extraction/components/ExtractionResultPanel.tsx` | New |
| `llm-extraction/components/ResultRow.tsx` | New |
| `llm-extraction/components/ResultCard.tsx` | New |
| `pages/LlmExtractionPage.tsx` | Modify — slim down |
| `i18n.ts` | Modify — new keys |
