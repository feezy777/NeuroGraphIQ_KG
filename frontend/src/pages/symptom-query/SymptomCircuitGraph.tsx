import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import type {
  NormalizedEdge,
  NormalizedNode,
  SymptomDisplayMode,
  SymptomGraphModel,
} from './symptomGraphTypes'
import { computeSymptomGraphVisibility } from './symptomGraphVisibility'
import { edgeDashForType, isErrorEdgeType, SYMPTOM_GRAPH_LEGEND, SYMPTOM_GRAPH_THEME } from './symptomGraphTheme'
import { stableNodePosition } from './normalizeSymptomGraph'

interface Point { x: number; y: number }

interface CircuitMeta {
  id: string
  circuit_name: string
  steps: { id: string; step_order: number; step_name: string; role: string }[]
}

interface Props {
  model: SymptomGraphModel
  selectedCircuit: CircuitMeta | null
  selectedCircuitId: string | null
  selectedStepIndex: number | null
  onSelectedStepIndexChange: (index: number | null) => void
  onEdgeSelect?: (edge: NormalizedEdge | null) => void
}

function truncate(value: string, length = 18): string {
  return value.length > length ? `${value.slice(0, length - 1)}…` : value
}

function samePoint(a: Point | undefined, b: Point): boolean {
  return Boolean(a && Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5)
}

function curvePath(edge: NormalizedEdge, positions: Map<string, Point>): string {
  const source = positions.get(edge.source)
  const target = positions.get(edge.target)
  if (!source || !target) return ''
  const dx = target.x - source.x
  const dy = target.y - source.y
  const length = Math.max(Math.hypot(dx, dy), 1)
  const normalX = -dy / length
  const normalY = dx / length
  const offset = (edge.parallelIndex - (edge.parallelTotal - 1) / 2) * 13
  const cx = (source.x + target.x) / 2 + normalX * offset
  const cy = (source.y + target.y) / 2 + normalY * offset
  return `M ${source.x} ${source.y} Q ${cx} ${cy} ${target.x} ${target.y}`
}

function resolveStepRegionIds(circuit: CircuitMeta | null, nodes: NormalizedNode[]): string[] {
  if (!circuit) return []
  const byLabel = new Map<string, string>()
  for (const node of nodes) {
    for (const label of [node.label, node.nameEn, node.nameCn]) {
      if (label) byLabel.set(label.trim().toLowerCase(), node.id)
    }
  }
  return circuit.steps.map(step => {
    const query = step.step_name.trim().toLowerCase()
    const exact = byLabel.get(query)
    if (exact) return exact
    const matched = nodes.find(node => {
      const names = [node.label, node.nameEn, node.nameCn]
        .filter(Boolean)
        .map(name => name.toLowerCase())
      return names.some(name => name.includes(query) || query.includes(name))
    })
    return matched?.id || ''
  })
}

export function SymptomCircuitGraph({
  model,
  selectedCircuit,
  selectedCircuitId,
  selectedStepIndex,
  onSelectedStepIndexChange,
  onEdgeSelect,
}: Props) {
  const hostRef = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ width: 900, height: 560 })
  const [displayMode, setDisplayMode] = useState<SymptomDisplayMode>('all_related')
  const [focusedNodeId, setFocusedNodeId] = useState<string | null>(null)
  const [hoveredNodeId, setHoveredNodeId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)
  const [relationFilter, setRelationFilter] = useState('all')
  const [minConfidence, setMinConfidence] = useState(0)
  const [searchQuery, setSearchQuery] = useState('')
  const [showBackgroundEdges, setShowBackgroundEdges] = useState(true)
  const [showLabels, setShowLabels] = useState(true)
  const [zoom, setZoom] = useState({ x: 0, y: 0, scale: 1 })
  const [positions, setPositions] = useState<Map<string, Point>>(new Map())
  const dragRef = useRef<{ nodeId?: string; pan?: Point; origin?: Point }>({})

  useEffect(() => {
    const host = hostRef.current
    if (!host) return
    const observer = new ResizeObserver(([entry]) => {
      const { width, height } = entry.contentRect
      setSize({ width: Math.max(width, 320), height: Math.max(height, 320) })
    })
    observer.observe(host)
    return () => observer.disconnect()
  }, [])

  const stepRegionIds = useMemo(
    () => resolveStepRegionIds(selectedCircuit, model.nodes),
    [selectedCircuit, model.nodes],
  )

  useEffect(() => {
    setPositions(previous => {
      const next = new Map(previous)
      for (const node of model.nodes) {
        const stable = stableNodePosition(node, size.width, size.height)
        if (!next.has(node.id)) next.set(node.id, stable)
      }
      for (const id of next.keys()) {
        if (!model.indexes.nodeById.has(id)) next.delete(id)
      }
      return next
    })
  }, [model.nodes, model.indexes.nodeById, size.height, size.width])

  useEffect(() => {
    if (!selectedCircuitId && displayMode === 'step_focus') setDisplayMode('all_related')
  }, [displayMode, selectedCircuitId])

  const visibility = useMemo(
    () => computeSymptomGraphVisibility(model, {
      displayMode,
      selectedCircuitId,
      selectedStepIndex,
      focusedNodeId,
      minConfidence,
      relationFilter,
      searchQuery,
      showBackgroundEdges,
      stepRegionIds,
    }),
    [
      displayMode, focusedNodeId, minConfidence, model, relationFilter, searchQuery,
      selectedCircuitId, selectedStepIndex, showBackgroundEdges, stepRegionIds,
    ],
  )

  const visibleNodeIds = useMemo(() => new Set(visibility.nodes.map(node => node.id)), [visibility.nodes])
  const hoveredEdgeIds = useMemo(
    () => new Set((hoveredNodeId ? model.indexes.edgesByNodeId.get(hoveredNodeId) || [] : []).map(edge => edge.id)),
    [hoveredNodeId, model.indexes.edgesByNodeId],
  )
  const hoveredNeighborIds = useMemo(() => {
    const neighbors = new Set<string>()
    if (!hoveredNodeId) return neighbors
    neighbors.add(hoveredNodeId)
    for (const edge of model.indexes.edgesByNodeId.get(hoveredNodeId) || []) {
      neighbors.add(edge.source === hoveredNodeId ? edge.target : edge.source)
    }
    return neighbors
  }, [hoveredNodeId, model.indexes.edgesByNodeId])
  const relationTypes = useMemo(
    () => [...new Set(model.edges.map(edge => edge.type))].sort(),
    [model.edges],
  )
  const selectedEdge = useMemo(
    () => visibility.edges.find(edge => edge.id === selectedEdgeId) || null,
    [selectedEdgeId, visibility.edges],
  )

  const resetLayout = useCallback(() => {
    const next = new Map<string, Point>()
    for (const node of model.nodes) next.set(node.id, stableNodePosition(node, size.width, size.height))
    setPositions(next)
    setZoom({ x: 0, y: 0, scale: 1 })
  }, [model.nodes, size.height, size.width])

  const fitView = useCallback(() => {
    const points = visibility.nodes.map(node => positions.get(node.id)).filter(Boolean) as Point[]
    if (points.length === 0) return
    const xs = points.map(point => point.x)
    const ys = points.map(point => point.y)
    const minX = Math.min(...xs); const maxX = Math.max(...xs)
    const minY = Math.min(...ys); const maxY = Math.max(...ys)
    const contentW = Math.max(maxX - minX, 100)
    const contentH = Math.max(maxY - minY, 100)
    const scale = Math.min(1.5, Math.max(0.45, Math.min((size.width - 80) / contentW, (size.height - 80) / contentH)))
    setZoom({
      scale,
      x: size.width / 2 - ((minX + maxX) / 2) * scale,
      y: size.height / 2 - ((minY + maxY) / 2) * scale,
    })
  }, [positions, size.height, size.width, visibility.nodes])

  const pointerToGraph = useCallback((event: React.PointerEvent<SVGSVGElement>): Point => {
    const bounds = event.currentTarget.getBoundingClientRect()
    return {
      x: (event.clientX - bounds.left - zoom.x) / zoom.scale,
      y: (event.clientY - bounds.top - zoom.y) / zoom.scale,
    }
  }, [zoom])

  const onPointerDown = useCallback((event: React.PointerEvent<SVGSVGElement>) => {
    const target = event.target as Element
    if (target.closest('[data-node-id], [data-edge-id]')) return
    dragRef.current = { pan: { x: event.clientX, y: event.clientY }, origin: { x: zoom.x, y: zoom.y } }
    event.currentTarget.setPointerCapture(event.pointerId)
    setFocusedNodeId(null)
    setSelectedEdgeId(null)
    onEdgeSelect?.(null)
  }, [onEdgeSelect, zoom.x, zoom.y])

  const onPointerMove = useCallback((event: React.PointerEvent<SVGSVGElement>) => {
    const drag = dragRef.current
    if (drag.nodeId) {
      const point = pointerToGraph(event)
      setPositions(previous => {
        const current = previous.get(drag.nodeId!)
        if (samePoint(current, point)) return previous
        const next = new Map(previous)
        next.set(drag.nodeId!, point)
        return next
      })
      return
    }
    if (drag.pan && drag.origin) {
      setZoom(current => ({
        ...current,
        x: drag.origin!.x + event.clientX - drag.pan!.x,
        y: drag.origin!.y + event.clientY - drag.pan!.y,
      }))
    }
  }, [pointerToGraph])

  const onPointerUp = useCallback(() => {
    dragRef.current = {}
  }, [])

  const onWheel = useCallback((event: React.WheelEvent<SVGSVGElement>) => {
    event.preventDefault()
    const bounds = event.currentTarget.getBoundingClientRect()
    const cursorX = event.clientX - bounds.left
    const cursorY = event.clientY - bounds.top
    const factor = event.deltaY < 0 ? 1.1 : 0.9
    setZoom(current => {
      const scale = Math.min(2.5, Math.max(0.35, current.scale * factor))
      return {
        scale,
        x: cursorX - ((cursorX - current.x) / current.scale) * scale,
        y: cursorY - ((cursorY - current.y) / current.scale) * scale,
      }
    })
  }, [])

  const nodeLabelVisible = useCallback((node: NormalizedNode) => {
    if (!showLabels) return false
    return zoom.scale >= 0.85 || node.id === focusedNodeId || node.circuitIds.includes(selectedCircuitId || '') || node.degree >= 5
  }, [focusedNodeId, selectedCircuitId, showLabels, zoom.scale])

  const edgeStyle = useCallback((edge: NormalizedEdge) => {
    const isCircuit = visibility.circuitPathEdgeIds.has(edge.id)
    const isActiveStep = visibility.activeStepEdgeIds.has(edge.id)
    const isHovered = hoveredEdgeIds.has(edge.id)
    const fadedByHover = hoveredNodeId && !isHovered
    const isError = edge.isInvalid || isErrorEdgeType(edge.type)
    const stroke = isError
      ? SYMPTOM_GRAPH_THEME.error
      : isActiveStep
        ? SYMPTOM_GRAPH_THEME.edgeCircuitActive
        : isCircuit
          ? SYMPTOM_GRAPH_THEME.edgeCircuit
          : isHovered
            ? SYMPTOM_GRAPH_THEME.edgeHover
            : SYMPTOM_GRAPH_THEME.edgeBackground
    return {
      stroke,
      strokeWidth: isActiveStep ? 4 : isCircuit ? 2.8 : isHovered ? 2 : 1,
      strokeOpacity: fadedByHover ? 0.08 : isCircuit ? 0.95 : isHovered ? 0.85 : 0.3,
      dash: edgeDashForType(edge.type),
    }
  }, [hoveredEdgeIds, hoveredNodeId, visibility.activeStepEdgeIds, visibility.circuitPathEdgeIds])

  const relationLabel = selectedEdge
    ? `${selectedEdge.type} · ${(selectedEdge.confidence * 100).toFixed(0)}% · ${selectedEdge.label}`
    : null

  return (
    <section style={{ height: '100%', minHeight: 0, display: 'flex', flexDirection: 'column', background: '#fff', border: '1px solid #e2e8f0', borderRadius: 10, overflow: 'hidden' }}>
      <div style={{ padding: '10px 12px', borderBottom: '1px solid #e2e8f0', display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 8 }}>
        <select className="form-input" value={relationFilter} onChange={event => setRelationFilter(event.target.value)} style={{ width: 128, fontSize: 12 }}>
          <option value="all">全部关系</option>
          {relationTypes.map(type => <option key={type} value={type}>{type}</option>)}
        </select>
        <label style={{ display: 'flex', alignItems: 'center', gap: 4, fontSize: 12, color: '#475569' }}>
          置信度 ≥ {minConfidence.toFixed(1)}
          <input type="range" min={0} max={100} value={Math.round(minConfidence * 100)} onChange={event => setMinConfidence(Number(event.target.value) / 100)} />
        </label>
        <input className="form-input" value={searchQuery} onChange={event => setSearchQuery(event.target.value)} placeholder="搜索脑区…" style={{ width: 150, fontSize: 12 }} />
        <select className="form-input" value={displayMode} onChange={event => setDisplayMode(event.target.value as SymptomDisplayMode)} style={{ width: 116, fontSize: 12 }}>
          <option value="all_related">全部相关</option>
          <option value="step_focus" disabled={!selectedCircuitId}>步骤聚焦</option>
          <option value="region_focus">脑区聚焦</option>
        </select>
        <label style={{ fontSize: 12, color: '#475569' }}><input type="checkbox" checked={showBackgroundEdges} onChange={event => setShowBackgroundEdges(event.target.checked)} /> 背景连接</label>
        <label style={{ fontSize: 12, color: '#475569' }}><input type="checkbox" checked={showLabels} onChange={event => setShowLabels(event.target.checked)} /> 标签</label>
        <span style={{ flex: 1 }} />
        <button className="btn btn-sm" onClick={fitView}>适配视图</button>
        <button className="btn btn-sm" onClick={resetLayout}>重置布局</button>
      </div>

      <div ref={hostRef} style={{ position: 'relative', flex: 1, minHeight: 360, background: '#f8fafc' }}>
        <svg
          width="100%"
          height="100%"
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={onPointerUp}
          onPointerLeave={onPointerUp}
          onWheel={onWheel}
          style={{ touchAction: 'none', cursor: dragRef.current.pan ? 'grabbing' : 'grab' }}
        >
          <defs>
            <marker id="symptom-path-arrow" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">
              <path d="M0,0 L0,6 L7,3 z" fill={SYMPTOM_GRAPH_THEME.edgeCircuit} />
            </marker>
          </defs>
          <g transform={`translate(${zoom.x},${zoom.y}) scale(${zoom.scale})`}>
            {visibility.edges.map(edge => {
              const style = edgeStyle(edge)
              return (
                <path
                  key={edge.id}
                  data-edge-id={edge.id}
                  d={curvePath(edge, positions)}
                  fill="none"
                  stroke={style.stroke}
                  strokeWidth={style.strokeWidth}
                  strokeOpacity={style.strokeOpacity}
                  strokeDasharray={style.dash}
                  markerEnd={visibility.circuitPathEdgeIds.has(edge.id) ? 'url(#symptom-path-arrow)' : undefined}
                  style={{ cursor: 'pointer' }}
                  onPointerDown={event => event.stopPropagation()}
                  onClick={event => {
                    event.stopPropagation()
                    setSelectedEdgeId(edge.id)
                    onEdgeSelect?.(edge)
                  }}
                />
              )
            })}
            {visibility.nodes.map(node => {
              const point = positions.get(node.id)
              if (!point) return null
              const isFocused = focusedNodeId === node.id
              const isCircuit = node.circuitIds.includes(selectedCircuitId || '')
              const hasHoverFocus = Boolean(hoveredNodeId && !hoveredNeighborIds.has(node.id))
              const radius = isFocused ? 13 : isCircuit ? 10 : Math.min(9, 6 + Math.sqrt(node.degree))
              return (
                <g
                  key={node.id}
                  data-node-id={node.id}
                  transform={`translate(${point.x},${point.y})`}
                  opacity={hasHoverFocus ? 0.35 : 1}
                  style={{ cursor: 'grab' }}
                  onPointerDown={event => {
                    event.stopPropagation()
                    dragRef.current = { nodeId: node.id }
                    event.currentTarget.ownerSVGElement?.setPointerCapture(event.pointerId)
                  }}
                  onClick={event => {
                    event.stopPropagation()
                    setFocusedNodeId(node.id)
                    setDisplayMode('region_focus')
                  }}
                  onMouseEnter={() => setHoveredNodeId(node.id)}
                  onMouseLeave={() => setHoveredNodeId(null)}
                >
                  {isFocused && <circle r={radius + 5} fill="none" stroke={SYMPTOM_GRAPH_THEME.nodeSelectedRing} strokeWidth={4} opacity={0.75} />}
                  <circle r={radius} fill={isFocused ? SYMPTOM_GRAPH_THEME.nodeSelected : isCircuit ? SYMPTOM_GRAPH_THEME.nodeCircuit : SYMPTOM_GRAPH_THEME.nodeDefault} stroke="#fff" strokeWidth={2} />
                  {nodeLabelVisible(node) && <text x={radius + 5} y={4} style={{ fontSize: 10, fill: SYMPTOM_GRAPH_THEME.labelDefault, pointerEvents: 'none', fontWeight: isCircuit || isFocused ? 600 : 400 }}>{truncate(node.shortLabel)}</text>}
                  <title>{`${node.nameEn || node.label}${node.nameCn ? ` / ${node.nameCn}` : ''}\nregion_id: ${node.id}\n连接数: ${node.degree}\n回路数: ${node.circuitIds.length}${node.nameMissing ? '\n名称待补全' : ''}`}</title>
                </g>
              )
            })}
          </g>
        </svg>
        {visibility.nodes.length === 0 && <div style={{ position: 'absolute', inset: 0, display: 'grid', placeItems: 'center', color: '#94a3b8', fontSize: 13 }}>当前筛选条件下没有可显示的脑区或连接</div>}
      </div>

      {selectedCircuit && (
        <div style={{ padding: '7px 12px', borderTop: '1px solid #e2e8f0', background: '#fff7ed', fontSize: 12, color: '#9a3412', overflowX: 'auto', whiteSpace: 'nowrap' }}>
          <strong>{selectedCircuit.circuit_name}</strong>
          {' · '}
          {selectedCircuit.steps.map((step, index) => (
            <span key={step.id}>
              {index > 0 && ' → '}
              <button type="button" onClick={() => onSelectedStepIndexChange(index)} style={{ color: selectedStepIndex === index ? '#c2410c' : '#9a3412', fontWeight: selectedStepIndex === index ? 700 : 400, border: 0, padding: 0, background: 'transparent', cursor: 'pointer' }}>{step.step_name}</button>
            </span>
          ))}
        </div>
      )}

      <div style={{ padding: '7px 12px', borderTop: '1px solid #e2e8f0', display: 'flex', flexWrap: 'wrap', gap: '4px 14px', fontSize: 11, color: '#64748b' }}>
        <span>当前回路：{selectedCircuit?.circuit_name || '未选择'}</span>
        <span>当前节点：{focusedNodeId ? model.indexes.nodeById.get(focusedNodeId)?.label || focusedNodeId : '未选择'}</span>
        <span>可见节点：{visibility.nodes.length}</span>
        <span>可见边：{visibility.edges.length}</span>
        <span>模式：{displayMode === 'all_related' ? '全部相关' : displayMode === 'step_focus' ? '步骤聚焦' : '脑区聚焦'}</span>
        {relationLabel && <span title={relationLabel}>当前连接：{truncate(relationLabel, 42)}</span>}
      </div>

      {import.meta.env.DEV && (
        <div style={{ padding: '6px 12px', borderTop: '1px dashed #cbd5e1', fontSize: 10, color: '#94a3b8' }}>
          调试：原始节点 {model.stats.rawNodeCount} · 原始边 {model.stats.rawEdgeCount} · 有效边 {model.stats.validEdgeCount} · 无效端点 {model.stats.invalidEndpointCount} · 重复边 {model.stats.duplicateEdgeCount} · 自环 {model.stats.selfLoopCount} · 可见节点 {visibility.nodes.length} · 可见边 {visibility.edges.length}
        </div>
      )}

      <div style={{ padding: '6px 12px', borderTop: '1px solid #f1f5f9', display: 'flex', gap: 12, flexWrap: 'wrap', fontSize: 10, color: '#64748b' }}>
        {SYMPTOM_GRAPH_LEGEND.map(item => <span key={item.label}><span style={{ color: item.color }}>{item.dash ? '╌╌' : '━━'}</span> {item.label}</span>)}
      </div>
    </section>
  )
}
