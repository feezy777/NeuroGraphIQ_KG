import { useState, useCallback } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { FinalKgGraphCanvas } from './FinalKgGraphCanvas'
import { FinalKgGraphSidebar, type GraphFilters } from './FinalKgGraphSidebar'
import { useGraphData } from './useGraphData'
import { useGlobalGranularity } from '../../hooks/useGlobalGranularity'
import '@xyflow/react/dist/style.css'
import './FinalKgGraphPage.css'

export function FinalKgGraphPage() {
  const { granularity: globalGranularity } = useGlobalGranularity()
  const [filters, setFilters] = useState<GraphFilters>({ atlas: '', granularity: globalGranularity, type: 'brain_region' })
  const [selectedNode, setSelectedNode] = useState<Record<string, unknown> | null>(null)
  const { nodes, edges, loading, error, loadGraph } = useGraphData()

  const handleSearch = useCallback(
    (params?: Record<string, string>) => {
      const merged: Record<string, string> = { ...params }
      if (filters.atlas) merged.source_atlas = filters.atlas
      merged.granularity_level = filters.granularity || globalGranularity
      if (filters.type) merged.center_type = filters.type
      if (!merged.depth) merged.depth = '1'
      if (!merged.include_functions) merged.include_functions = 'true'
      if (!merged.limit) merged.limit = '200'
      loadGraph(merged)
    },
    [filters, loadGraph, globalGranularity],
  )

  const handleExpandNode = useCallback(
    (nodeId: string) => {
      loadGraph({
        center_type: 'brain_region',
        centerId: nodeId,
        depth: '1',
        include_functions: 'true',
        limit: '200',
        granularity_level: filters.granularity || globalGranularity,
      })
    },
    [loadGraph, filters.granularity, globalGranularity],
  )

  return (
    <div className="graph-explorer-page">
      <ReactFlowProvider>
        <FinalKgGraphSidebar
          filters={filters}
          onFiltersChange={setFilters}
          selectedNode={selectedNode}
          onSearch={handleSearch}
        />
        <FinalKgGraphCanvas
          nodes={nodes}
          edges={edges}
          loading={loading}
          error={error}
          onNodeClick={node => setSelectedNode(node as unknown as Record<string, unknown>)}
          onExpandNode={handleExpandNode}
        />
      </ReactFlowProvider>
    </div>
  )
}
