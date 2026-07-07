// ── Shared progress data for extraction workflow progress/result panels ─────

export interface ProgressData {
  workflowRunId: string
  workflowStatus: string
  progressPercent: number
  processedPacks: number
  totalPacks: number
  successPacks: number          // succeeded_pack_count — packs that finished without error
  failedPacks: number            // failed_pack_count — transport/parse/exception failures
  noConnectionPacks: number      // no_connection_pack_count — succeeded but zero connections found
  noFindingsPacks: number         // no_findings_pack_count — LLM responded but found no connections (legitimate)
  connectionsFound: number       // parsed_projection_count
  screenedLikelyCount: number     // screened_likely_connection_count
  functionCount: number           // parsed_function_count
  parsedNoConnCount: number      // parsed_no_connection_count
  createdCount: number            // created_projection_count — new Mirror connections written
  updatedCount: number            // updated_projection_count — merged into existing
  mergedCount: number             // merged_projection_count — dedup-merged into existing
  skippedDupCount: number         // skipped_duplicate_count — exact duplicates skipped
  noConnectionCount: number       // no_connection_count — all no_connection entries
  providerCallCount: number
  modelCalls: number              // model_call_count — packs built, waiting for provider
  promptSent: number              // prompt_sent_count — provider request in flight
  inFlightPacks: number           // in_flight_pack_count — backend reports current in-flight packs
  concurrency: number
  averagePackSec: number | null   // null = not available yet
  estimatedRemainingSec: number | null
  zeroDiags: string[]
  errors: string[]
  elapsedSec: number
  startedAt: string | null
  lastPauseResponse: string
  lastPauseError: string
  lastCancelResponse: string
  lastCancelError: string
  estimatedInputTokens: number
  estimatedOutputTokens: number
  actualPromptTokens: number
  actualCompletionTokens: number
  dryRunSamplePack: boolean
}
