# Unified Extraction Run Modal — All Tasks + Prompt + Parameters

**Date:** 2026-06-24 | **Status:** implementing

## Summary

Extend `ExtractionRunModal` to cover ALL extraction types (composite AND single-step), with built-in prompt template selection/editing and configurable execution parameters.

## Architecture

```
handleBatchExtract() → setShowRunModal(true)  (all task types)

ExtractionRunModal (4-phase: confirm | running | complete)
  confirm phase:
    [参数 Tab]  temperature, max_tokens, task-specific params, create_* toggles
    [提示词 Tab] template dropdown, editable system/user prompt textareas
  running phase:
    composite: poll backend → per-step progress
    single: await API → single-step progress
  complete phase:
    counts + nav buttons
```

## Eliminated

| Removed | Reason |
|---------|--------|
| `CompositeConfirmDialog` | Replaced by modal confirm phase |
| `BulkRunStatusPanel` | Replaced by modal running phase |
| `DataFirstCandidatesTab` ConfirmDialog | Replaced by modal |
| `useBulkExtraction` hook usage | Modal calls API directly |
| `bulkConfirmTrigger` state | Unified `showRunModal` |

## Files

| File | Action |
|------|--------|
| `components/ExtractionRunModal.tsx` | Rewrite — 4-phase + tabs + single/composite unified |
| `LlmExtractionPage.tsx` | Simplify — remove old dialogs, unify entry |
| `components/DataFirstCandidatesTab.tsx` | Simplify — remove bulk extraction logic |
| `i18n.ts` | Add — param labels, prompt keys |
| `styles.css` | Add — slider, prompt textarea styles |
