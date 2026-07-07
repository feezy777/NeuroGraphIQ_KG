# Background Task Center

Date: 2026-07-03. Unified task monitoring with top-nav dropdown + sidebar page.

## Components

- `useBackgroundTasks.ts` — hook polling both APIs every 3s, returns unified BgTask[]
- `TaskCenterDropdown.tsx` — top-nav icon with badge, dropdown panel showing running tasks
- `BackgroundTaskCenter.tsx` — sidebar full page with tabs (running/completed/failed), expandable task detail

## Modified

- `WorkbenchLayout.tsx` — add bell icon + menu item "任务中心"

## No backend changes
