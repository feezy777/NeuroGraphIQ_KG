# Background Task Center v2 — Full Console Redesign

Full layout overhaul: stats bar + filter sidebar + card grid + detail drawer + original modal recall.

## Components
- TaskCenterHeader — title + 6 stat cards + search/refresh
- TaskCenterFilters — status/type/time/sort sidebar
- TaskCardList + TaskCard — rich card grid with 4 info columns
- TaskDetailDrawer — right slide-in detail panel
- Reuses: FieldCompletionStatsCards, TaskDetailModal (context)

## Layout: 3-section
```
┌──────────────────────────────────────────────────┐
│ 后台任务中心                      [搜索] [刷新]  │
│ [全部 12] [进行中 3] [排队 1] ... [异常 2]      │
├────────┬─────────────────────────────────────────┤
│ 筛选   │ ┌──────────────────────────────────┐   │
│ 状态   │ │ 任务卡片 1                        │   │
│ 类型   │ │ 任务卡片 2                        │   │
│ 时间   │ │ 任务卡片 3                        │   │
│ 排序   │ │ ...                               │   │
│        │ └──────────────────────────────────┘   │
└────────┴─────────────────────────────────────────┘
```
