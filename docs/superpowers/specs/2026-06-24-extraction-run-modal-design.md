# Extraction Run Modal — Simplified Execution UI

**Date:** 2026-06-24 | **Status:** implementing

## Summary

Replace the complex ExtractionResultModal (1185 lines, progress bars, provider audit, workflow events) with a simpler ExtractionRunModal modeled after FieldCompletionModal (3-stage: confirm → running → complete).

## Design

```
confirm stage → running stage (per-step pack progress) → complete stage (counts + actions)
```

- **Failed items are silently skipped** — they count as "skipped", never block the task
- **No progress bar** — per-step status line with pack counts instead
- **No provider audit / workflow events / parse diagnostics**
- **Removed from render:** ProgressPanel, ExtractionRunFloatingWidget, CompositeStatusPanel
- **Polling:** retained at 2s intervals

## Files

| File | Action |
|------|--------|
| `components/ExtractionRunModal.tsx` | New — 3-stage modal |
| `services/compositeExtractionRunner.ts` | Simplify — strip audit/diagnostics from callbacks |
| `LlmExtractionPage.tsx` | Modify — swap modal, remove floating widget |
