import { useMemo, useCallback, useState, useRef, useEffect, type MouseEvent } from 'react'
import {
  ReactFlow,
  Background,
  Controls,
  MiniMap,
  Handle,
  Position,
  useNodesState,
  useEdgesState,
  type NodeProps,
  type EdgeProps,
  type Node,
  type Edge,
  MarkerType,
  BaseEdge,
  getStraightPath,
} from '@xyflow/react'
import type { GraphExplorerNode, GraphExplorerEdge } from './useGraphData'

// ── Colour palette ──────────────────────────────────────────────────────────────
const COLORS: Record<string, string> = {
  macro: '#3b82f6',
  meso: '#22c55e',
  sub: '#f97316',
  fine: '#8b5cf6',
  molecular: '#ec4899',
}
const DEFAULT_NODE_COLOR = '#6b7280'

function nodeColor(nodeType?: string, metadata?: Record<string, unknown>): string {
  const granularity =
    (metadata?.granularity_family as string) ||
    (metadata?.granularity_level as string) ||
    ''
  for (const [key, color] of Object.entries(COLORS)) {
    if (granularity.includes(key)) return color
  }
  return DEFAULT_NODE_COLOR
}

// ── Custom Node Components ──────────────────────────────────────────────────────

function BrainRegionNode({ data, selected }: NodeProps) {
  const color = nodeColor(data.nodeType as string, data.metadata as Record<string, unknown>)
  return (
    <div
      className="graph-node graph-node-region"
      style={{
        borderColor: selected ? '#1d4ed8' : color,
        boxShadow: selected ? `0 0 0 2px ${color}40` : undefined,
      }}
      title={`${data.label as string} (${(data.nodeType as string) || 'brain_region'})`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="graph-node-shape" style={{ background: color }} />
      <div className="graph-node-label">{data.label as string}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

function CircuitNode({ data, selected }: NodeProps) {
  const color = nodeColor(data.nodeType as string, data.metadata as Record<string, unknown>)
  return (
    <div
      className="graph-node graph-node-circuit"
      style={{
        borderColor: selected ? '#1d4ed8' : color,
        boxShadow: selected ? `0 0 0 2px ${color}40` : undefined,
      }}
      title={`${data.label as string} (circuit)`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="graph-node-shape graph-node-shape-diamond" style={{ background: color }} />
      <div className="graph-node-label">{data.label as string}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function FunctionNode({ data, selected }: NodeProps) {
  const color = nodeColor(data.nodeType as string, data.metadata as Record<string, unknown>)
  return (
    <div
      className="graph-node graph-node-function"
      style={{
        borderColor: selected ? '#1d4ed8' : color,
        boxShadow: selected ? `0 0 0 2px ${color}40` : undefined,
      }}
      title={`${data.label as string} (function)`}
    >
      <Handle type="target" position={Position.Top} />
      <div className="graph-node-shape graph-node-shape-triangle" style={{ background: color }} />
      <div className="graph-node-label">{data.label as string}</div>
      <Handle type="source" position={Position.Bottom} />
    </div>
  )
}

function CircuitStepNode({ data, selected }: NodeProps) {
  const color = nodeColor(data.nodeType as string, data.metadata as Record<string, unknown>)
  return (
    <div
      className="graph-node graph-node-step"
      style={{
        borderColor: selected ? '#1d4ed8' : color,
        boxShadow: selected ? `0 0 0 2px ${color}40` : undefined,
      }}
      title={`${data.label as string} (circuit_step)`}
    >
      <Handle type="target" position={Position.Left} />
      <div className="graph-node-shape graph-node-shape-sm" style={{ background: color }} />
      <div className="graph-node-label">{data.label as string}</div>
      <Handle type="source" position={Position.Right} />
    </div>
  )
}

const nodeTypes = {
  brain_region: BrainRegionNode,
  circuit: CircuitNode,
  function: FunctionNode,
  circuit_step: CircuitStepNode,
  default: BrainRegionNode,
}

// ── Edge Styles ─────────────────────────────────────────────────────────────────
const EDGE_STYLES: Record<string, { stroke: string; strokeWidth: number; strokeDasharray?: string }> = {
  structural_connection: { stroke: '#1e40af', strokeWidth: 2 },
  functional_connection: { stroke: '#ea580c', strokeWidth: 2 },
  has_function: { stroke: '#ca8a04', strokeWidth: 1, strokeDasharray: '5 5' },
  default: { stroke: '#94a3b8', strokeWidth: 1 },
}

function CustomEdge({
  id,
  source,
  target,
  sourceX,
  sourceY,
  targetX,
  targetY,
  data,
  selected,
}: EdgeProps) {
  const edgeType = (data?.edgeType as string) || 'default'
  const style = EDGE_STYLES[edgeType] || EDGE_STYLES.default
  const [edgePath] = getStraightPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
  })

  return (
    <BaseEdge
      id={id}
      path={edgePath}
      style={{
        ...style,
        stroke: selected ? '#f59e0b' : style.stroke,
      }}
      markerEnd={MarkerType.ArrowClosed}
    />
  )
}

const edgeTypes = {
  structural_connection: CustomEdge,
  functional_connection: CustomEdge,
  has_function: CustomEdge,
  default: CustomEdge,
}

// ── Context Menu ────────────────────────────────────────────────────────────────
interface ContextMenuState {
  x: number
  y: number
  nodeId: string
}

// ── Canvas Component ────────────────────────────────────────────────────────────
interface FinalKgGraphCanvasProps {
  nodes: GraphExplorerNode[]
  edges: GraphExplorerEdge[]
  loading: boolean
  error: string | null
  onNodeClick: (node: GraphExplorerNode | null) => void
  onExpandNode: (nodeId: string) => void
}

export function FinalKgGraphCanvas({
  nodes: inputNodes,
  edges: inputEdges,
  loading,
  error,
  onNodeClick,
  onExpandNode,
}: FinalKgGraphCanvasProps) {
  const [rfNodes, setRfNodes, onNodesChange] = useNodesState(inputNodes as Node[])
  const [rfEdges, setRfEdges, onEdgesChange] = useEdgesState(inputEdges as Edge[])
  const [contextMenu, setContextMenu] = useState<ContextMenuState | null>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  // Sync external data changes
  useEffect(() => {
    setRfNodes(inputNodes as Node[])
  }, [inputNodes, setRfNodes])

  useEffect(() => {
    setRfEdges(inputEdges as Edge[])
  }, [inputEdges, setRfEdges])

  const onNodeClickHandler = useCallback(
    (_event: React.MouseEvent, node: Node) => {
      onNodeClick(node as unknown as GraphExplorerNode)
    },
    [onNodeClick],
  )

  const onPaneClick = useCallback(() => {
    setContextMenu(null)
  }, [])

  const onNodeContextMenu = useCallback(
    (event: MouseEvent, node: Node) => {
      event.preventDefault()
      setContextMenu({ x: event.clientX, y: event.clientY, nodeId: node.id })
    },
    [],
  )

  const handleExpand = useCallback(() => {
    if (contextMenu) {
      onExpandNode(contextMenu.nodeId)
      setContextMenu(null)
    }
  }, [contextMenu, onExpandNode])

  const handleHideDetails = useCallback(() => {
    onNodeClick(null)
    setContextMenu(null)
  }, [onNodeClick])

  // Close context menu on click outside
  useEffect(() => {
    const handleClick = () => setContextMenu(null)
    if (contextMenu) {
      document.addEventListener('click', handleClick)
    }
    return () => document.removeEventListener('click', handleClick)
  }, [contextMenu])

  const defaultEdgeOptions = useMemo(
    () => ({
      style: { stroke: '#94a3b8', strokeWidth: 1 },
      type: 'default',
      markerEnd: { type: MarkerType.ArrowClosed } as const,
    }),
    [],
  )

  if (loading) {
    return (
      <div className="graph-canvas-container">
        <div className="graph-loading-overlay">
          <div className="graph-spinner" />
          <span>Loading graph data...</span>
        </div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="graph-canvas-container">
        <div className="graph-error-banner">
          <strong>Error:</strong> {error}
          <button onClick={() => window.location.reload()} type="button" className="graph-error-retry">
            Retry
          </button>
        </div>
      </div>
    )
  }

  return (
    <div className="graph-canvas-container">
      <ReactFlow
        nodes={rfNodes}
        edges={rfEdges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        nodeTypes={nodeTypes}
        edgeTypes={edgeTypes}
        defaultEdgeOptions={defaultEdgeOptions}
        onNodeClick={onNodeClickHandler}
        onNodeContextMenu={onNodeContextMenu}
        onPaneClick={onPaneClick}
        fitView
        attributionPosition="bottom-left"
      >
        <Background variant={'dots' as any} gap={20} size={1} color="#e2e8f0" />
        <Controls showInteractive={false} />
        <MiniMap
          nodeStrokeWidth={3}
          nodeColor={n => {
            const meta = (n as Node).data?.metadata as Record<string, unknown> | undefined
            return nodeColor((n as Node).data?.nodeType as string, meta)
          }}
          maskColor="rgba(0,0,0,0.08)"
          style={{ border: '1px solid #e2e8f0' }}
        />
      </ReactFlow>

      {contextMenu && (
        <div
          ref={menuRef}
          className="graph-context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
        >
          <button type="button" onClick={handleExpand} className="graph-context-item">
            Expand
          </button>
          <button type="button" onClick={handleHideDetails} className="graph-context-item">
            Hide Details
          </button>
        </div>
      )}
    </div>
  )
}
