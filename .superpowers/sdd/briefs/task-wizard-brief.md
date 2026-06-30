# Pool 提取弹窗两步分页 + 脑区名称修正 实施计划

> **For agentic workers:** Single file, single task. Implement all changes in sequence.

**Goal:** PoolExtractionModal 单页改两步分页 + 脑区名称列显示中文名

**Architecture:** 仅改 `PoolExtractionModal.tsx`。新增 wizardStep 状态切分 renderPrepare 为 renderStep1/renderStep2。新增 fetchCandidates 调用构建内部 labels map。

**Spec:** `docs/superpowers/specs/2026-06-30-pool-extraction-wizard-design.md`

## Global Constraints
- 不改后端
- `handleStartExtraction` 零改动
- Progress/Result 两态不动
- `npm run build` 零 TS 错误

## Task: All changes in PoolExtractionModal.tsx

### Files
- Modify: `frontend/src/pages/llm-extraction/components/PoolExtractionModal.tsx`

### Changes

**A. Imports**: Add `fetchCandidates` import from endpoints.

**B. State**: Add `wizardStep` state (1|2), reset on close.

**C. Internal labels**: Add useEffect to fetch candidates when pool loads, build `candidateLabels` map from `cn_name ?? en_name ?? raw_name`.

**D. DisplayMember label**: Update useMemo to use internal labels with name fallback.

**E. Split renderPrepare**: 
- `renderStep1()`: scope info + search bar + action buttons + member table. Footer: 取消/下一步.
- `renderStep2()`: scope summary line + ModelSelector + Dry run. Footer: 上一步/取消/开始提取.

**F. Table column fix**: "脑区名称" column uses `cn_name ?? en_name ?? raw_name`; search placeholder "搜索 ID 或名称..."; search logic matches both.

**G. Render switch**: `modalState === 'prepare'` renders step1 or step2 based on wizardStep.

### Verification
- `cd frontend && npm run build` — zero TS errors
