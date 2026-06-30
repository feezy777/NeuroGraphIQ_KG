# Task Modal 1 Report: Enhance useCandidatePool hook

## Status: DONE

## Changes Made

**File:** `frontend/src/pages/llm-extraction/hooks/useCandidatePool.ts`

Three new methods added to the hook:

### 1. `batchRemove(candidateIds: string[])`
Removes multiple candidates from the pool in a single API call. If removing all remaining candidates, sets pool to `null`. Otherwise re-fetches the full pool to refresh membership. Uses `removePoolMembers` from the API layer. (lines 116-132)

### 2. `searchCandidates(query: string): Promise<any[]>`
Searches for candidates via the API using the current `scope` (source atlas, granularity level/family) and a text query. Returns up to 20 results. Uses dynamic import of `listCandidates` to avoid circular dependency risk. (lines 134-150)

### 3. `refresh()`
Re-fetches the current pool by ID. Sets pool to `null` if the pool now has 0 candidates. Silently catches errors (no console noise for transient failures). (lines 152-158)

### Return object updated
All three new methods are included in the hook's return value (line 170-174).

## Verification

- `npx tsc --noEmit --pretty` completed with **zero TypeScript errors** related to this file.
- No changes to the existing API (`pool`, `pooledCandidateIds`, `isLoading`, `addCandidates`, `removeCandidate`, `clearPool`) — fully backward compatible.
