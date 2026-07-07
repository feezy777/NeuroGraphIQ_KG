import { useState, useCallback } from 'react'
import { ReactFlowProvider } from '@xyflow/react'
import { FinalKgGraphCanvas } from './FinalKgGraphCanvas'
import { FinalKgGraphSidebar } from './FinalKgGraphSidebar'
import { useGraphData } from './useGraphData'
import '@xyflow/react/dist/style.css'
import './FinalKgGraphPage.css'

export function FinalKgGraphPage() {
  const [filters, setFilters] = useState({ atlas: '', granularity: '', type: 'brain_region' })
  const [selectedNode, setSelectedNode] = useState<Record<string, unknown> | null>(null)
  const { nodes, edges, loading, error, loadGraph } = useGraphData()

  const handleSearch = useCallback(
    (params?: Record<string, string>) => {
      const merged: Record<string, string> = { ...params }
      if (filters.atlas) merged.source_atlas = filters.atlas
      if (filters.granularity) merged.granularity_level = filters.granularity
      if (filters.type) merged.center_type = filters.type
      if (!merged.depth) merged.depth = '1'
      if (!merged.include_functions) merged.include_functions = 'true'
      if (!merged.limit) merged.limit = '200'
      loadGraph(merged)
    },
    [filters, loadGraph],
  )

  const handleExpandNode = useCallback(
    (nodeId: string) => {
      loadGraph({
        center_type: 'brain_region',
        centerId: nodeId,
        depth: '1',
        include_functions: 'true',
        limit: '200',
      })
    },
    [loadGraph],
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
