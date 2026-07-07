import { useState, useCallback } from 'react'
import { buildApiUrl } from '../../api/client'
import type { FinalGraphResponse } from '../../api/endpoints'

export interface GraphExplorerNode {
  id: string
  type: string
  position: { x: number; y: number }
  data: Record<string, unknown>
}

export interface GraphExplorerEdge {
  id: string
  source: string
  target: string
  type?: string
  label?: string | null
  data?: Record<string, unknown>
}

export function useGraphData() {
  const [nodes, setNodes] = useState<GraphExplorerNode[]>([])
  const [edges, setEdges] = useState<GraphExplorerEdge[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const loadGraph = useCallback(async (params?: Record<string, string>) => {
    setLoading(true)
    setError(null)
    try {
      const query = new URLSearchParams(
        params || {
          center_type: 'brain_region',
          depth: '1',
          include_functions: 'true',
          limit: '200',
        },
      )
      const url = buildApiUrl(`/api/final-macro-clinical/browser/graph?${query}`)
      const res = await fetch(url)
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const data: FinalGraphResponse = await res.json()
      setNodes(
        (data.nodes || []).map(n => ({
          id: n.id,
          type: n.type || 'default',
          position: { x: Math.random() * 500, y: Math.random() * 500 },
          data: {
            ...n,
            label: n.label || n.id,
            nodeType: n.type,
          },
        })),
      )
      setEdges(
        (data.edges || []).map(e => ({
          id: e.id,
          source: e.source,
          target: e.target,
          label: e.label,
          type: e.type || 'default',
          data: { edgeType: e.type, predicate: e.predicate },
        })),
      )
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to load graph')
    } finally {
      setLoading(false)
    }
  }, [])

  return { nodes, edges, loading, error, loadGraph }
}
