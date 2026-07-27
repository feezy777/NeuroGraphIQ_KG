/**
 * Major96Brain3DView.tsx — Pure Three.js 3D brain viewer + connections.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import * as THREE from 'three'
import { OrbitControls } from 'three/examples/jsm/controls/OrbitControls.js'
import { mniToScene, isValidMniPoint } from '../../lib/brain-spatial/mniSceneTransform'
import { fetchBrainSurface } from '../../lib/brain-spatial/loadMajor96SpatialData'
import { VIEW_PRESETS, BRAIN_SURFACE_OPACITY_DEFAULT, BRAIN_SURFACE_COLOR, NODE_COLORS } from '../../lib/brain-spatial/brain3d.constants'
import type { BrainRegionNode, ViewPreset } from '../../lib/brain-spatial/brain3d.types'

const VIEW_NAMES: Record<ViewPreset, string> = {
  default: '默认', 'left-lateral': '左外侧', 'right-lateral': '右外侧',
  anterior: '前视图', posterior: '后视图', superior: '顶视图', inferior: '底视图',
}

interface MacroConnection {
  id: string; source_name: string; target_name: string
  confidence: number; connection_type: string
}

interface Props {
  nodes: BrainRegionNode[]
  onSelectNode: (node: BrainRegionNode | null) => void
  selectedNode: BrainRegionNode | null
}

export function Major96Brain3DView({ nodes, onSelectNode, selectedNode }: Props) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [showLeft, setShowLeft] = useState(true)
  const [showRight, setShowRight] = useState(true)
  const [showNodes, setShowNodes] = useState(true)
  const [surfaceOpacity, setSurfaceOpacity] = useState(BRAIN_SURFACE_OPACITY_DEFAULT)
  const [nodeRadius, setNodeRadius] = useState(1.8)
  const [hoveredNode, setHoveredNode] = useState<BrainRegionNode | null>(null)
  const [viewPreset, setViewPreset] = useState<ViewPreset>('default')
  const [showConnections, setShowConnections] = useState(false)
  const [connMinConf, setConnMinConf] = useState(0.5)
  const [connCount, setConnCount] = useState(0)
  const [connTotal, setConnTotal] = useState(0)
  const [loadedConns, setLoadedConns] = useState<MacroConnection[] | null>(null)
  const [initError, setInitError] = useState<string | null>(null)
  const sceneRef = useRef<{
    scene: THREE.Scene; camera: THREE.PerspectiveCamera; controls: OrbitControls;
    renderer: THREE.WebGLRenderer; nodeMeshes: Map<string, THREE.Mesh>;
    surfaceGroups: { left: THREE.Group; right: THREE.Group };
    connGroup: THREE.Group;
    allConnections: MacroConnection[];
    coloredData: { left: any; right: any } | null;
    highlightGroup: THREE.Group;
  } | null>(null)
  const connLinesRef = useRef<THREE.LineSegments | null>(null)
  const highlightRef = useRef<THREE.Group>(new THREE.Group())

  // Initialize Three.js
  useEffect(() => {
    const container = containerRef.current
    if (!container) return

    try {
      const w = container.clientWidth
      const h = container.clientHeight

      const scene = new THREE.Scene()
      scene.background = new THREE.Color('#1a1a2e')

      const camera = new THREE.PerspectiveCamera(45, w / Math.max(h, 1), 1, 1000)
      camera.position.set(0, 0, 200)

      const renderer = new THREE.WebGLRenderer({ antialias: true })
      renderer.setSize(w, h)
      renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
      container.appendChild(renderer.domElement)

      const controls = new OrbitControls(camera, renderer.domElement)
      controls.enableDamping = true
      controls.dampingFactor = 0.1

      // Lights
      scene.add(new THREE.AmbientLight(0xffffff, 0.6))
      const d1 = new THREE.DirectionalLight(0xffffff, 0.8)
      d1.position.set(100, 100, 100)
      scene.add(d1)
      const d2 = new THREE.DirectionalLight(0xffffff, 0.3)
      d2.position.set(-50, -50, -50)
      scene.add(d2)

      const surfaceGroups = { left: new THREE.Group(), right: new THREE.Group() }
      scene.add(surfaceGroups.left)
      scene.add(surfaceGroups.right)

      const connGroup = new THREE.Group()
      scene.add(connGroup)

      const highlightGroup = new THREE.Group()
      scene.add(highlightGroup)
      highlightRef.current = highlightGroup

      const nodeMeshes = new Map<string, THREE.Mesh>()

      const state = { scene, camera, controls, renderer, nodeMeshes, surfaceGroups, connGroup, allConnections: [], coloredData: null, highlightGroup }
      sceneRef.current = state

      // Raycaster for click/hover
      const raycaster = new THREE.Raycaster()
      const mouse = new THREE.Vector2()

      const onPointerMove = (e: MouseEvent) => {
        const rect = renderer.domElement.getBoundingClientRect()
        mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
        mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1

        raycaster.setFromCamera(mouse, camera)
        const hits = raycaster.intersectObjects([...nodeMeshes.values()])
        if (hits.length > 0) {
          const mesh = hits[0].object as THREE.Mesh
          const nodeId = mesh.userData.nodeId as string
          const node = nodes.find(n => (n.region_id || n.name_en) === nodeId) || null
          setHoveredNode(node)
        } else {
          setHoveredNode(null)
        }
      }

      const onClick = (e: MouseEvent) => {
        const rect = renderer.domElement.getBoundingClientRect()
        mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1
        mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1

        raycaster.setFromCamera(mouse, camera)
        const hits = raycaster.intersectObjects([...nodeMeshes.values()])
        if (hits.length > 0) {
          const mesh = hits[0].object as THREE.Mesh
          const nodeId = mesh.userData.nodeId as string
          const node = nodes.find(n => (n.region_id || n.name_en) === nodeId) || null
          onSelectNode(node)
        } else {
          onSelectNode(null)
        }
      }

      renderer.domElement.addEventListener('pointermove', onPointerMove)
      renderer.domElement.addEventListener('click', onClick)

      // Animation loop
      let animId: number
      const animate = () => {
        animId = requestAnimationFrame(animate)
        controls.update()
        renderer.render(scene, camera)
      }
      animate()

      // Resize handler
      const onResize = () => {
        const cw = container.clientWidth
        const ch = container.clientHeight
        camera.aspect = cw / Math.max(ch, 1)
        camera.updateProjectionMatrix()
        renderer.setSize(cw, ch)
      }
      window.addEventListener('resize', onResize)

      return () => {
        cancelAnimationFrame(animId)
        window.removeEventListener('resize', onResize)
        renderer.domElement.removeEventListener('pointermove', onPointerMove)
        renderer.domElement.removeEventListener('click', onClick)
        renderer.dispose()
        controls.dispose()
        if (container.contains(renderer.domElement)) {
          container.removeChild(renderer.domElement)
        }
      }
    } catch (e: any) {
      console.error('[Brain3D] Init error:', e)
      setInitError(e.message || 'WebGL initialization failed')
    }
  }, [])

  // Load brain surfaces
  useEffect(() => {
    const state = sceneRef.current
    if (!state) return

    const loadSurface = async (hemi: 'left' | 'right') => {
      try {
        const mesh = await fetchBrainSurface(hemi)
        const geo = new THREE.BufferGeometry()
        const verts: number[] = []
        for (const v of mesh.vertices) verts.push(v[0], v[2], -v[1])
        const indices: number[] = []
        for (const f of mesh.faces) indices.push(f[0], f[1], f[2])
        geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3))
        geo.setIndex(indices)
        geo.computeVertexNormals()
        const mat = new THREE.MeshPhongMaterial({
          color: BRAIN_SURFACE_COLOR, transparent: true, opacity: surfaceOpacity,
          side: THREE.DoubleSide, depthWrite: false,
        })
        const surfaceMesh = new THREE.Mesh(geo, mat)
        state.surfaceGroups[hemi].add(surfaceMesh)
      } catch (e) {
        console.warn(`[Brain3D] Surface ${hemi} load failed:`, e)
      }
    }
    loadSurface('left')
    loadSurface('right')
  }, [])

  // Pre-load colored surface data for highlight
  useEffect(() => {
    const load = async () => {
      try {
        const [left, right] = await Promise.all([
          fetch('/brain_3d/major96/brain_left_colored.json').then(r => r.json()),
          fetch('/brain_3d/major96/brain_right_colored.json').then(r => r.json()),
        ])
        const state = sceneRef.current
        if (state) state.coloredData = { left, right }
      } catch (e) { console.warn('[Brain3D] Colored data preload failed:', e) }
    }
    load()
  }, [])

  // Load node→AAL label mapping
  const [labelMap, setLabelMap] = useState<Record<string, number> | null>(null)
  useEffect(() => {
    fetch('/brain_3d/major96/node_label_map.json')
      .then(r => r.json()).then(setLabelMap)
      .catch(() => {})
  }, [])

  // Highlight selected node's region on brain surface
  useEffect(() => {
    const state = sceneRef.current
    if (!state) return
    highlightRef.current.clear()
    if (!selectedNode || !state.coloredData || !labelMap) {
      // Restore gray surfaces
      state.surfaceGroups.left.visible = showLeft
      state.surfaceGroups.right.visible = showRight
      return
    }

    const nodeName = (selectedNode.name_en || '').toLowerCase().trim()
    const targetLabel = labelMap[nodeName]
    if (!targetLabel) {
      state.surfaceGroups.left.visible = showLeft
      state.surfaceGroups.right.visible = showRight
      return
    }

    // Determine hemisphere from laterality
    const hemi: 'left' | 'right' = selectedNode.laterality === 'left' ? 'left' : 'right'
    const data = state.coloredData[hemi]
    if (!data) return

    // Filter vertices: only keep those belonging to the target AAL label
    // The colored mesh has vertex positions (MNI) and colors (HSL from label)
    // We need to read the original atlas to check which vertices match the target label
    // For now, highlight by showing colored overlay for the matching hemisphere
    // with a bright outline effect

    const verts: number[] = []
    for (const v of data.vertices) verts.push(v[0], v[2], -v[1])
    const indices: number[] = []
    for (const f of data.faces) indices.push(f[0], f[1], f[2])

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.Float32BufferAttribute(verts, 3))
    geo.setIndex(indices)
    geo.computeVertexNormals()

    const mat = new THREE.MeshPhongMaterial({
      color: 0x00D4FF, transparent: true, opacity: 0.5,
      side: THREE.DoubleSide, depthWrite: false, emissive: 0x003344, emissiveIntensity: 0.3,
    })
    const mesh = new THREE.Mesh(geo, mat)
    highlightRef.current.add(mesh)

    // Hide the gray surface for the highlighted hemisphere
    state.surfaceGroups[hemi].visible = false
  }, [selectedNode, labelMap, showLeft, showRight])

  // Restore surfaces when selection cleared
  useEffect(() => {
    if (selectedNode) return
    const state = sceneRef.current
    if (!state) return
    state.surfaceGroups.left.visible = showLeft
    state.surfaceGroups.right.visible = showRight
    highlightRef.current.clear()
  }, [selectedNode, showLeft, showRight])

  // Restore surface when selection cleared
  useEffect(() => {
    if (selectedNode) return
    const state = sceneRef.current
    if (!state) return
    state.surfaceGroups.left.visible = showLeft
    state.surfaceGroups.right.visible = showRight
    highlightRef.current.clear()
  }, [selectedNode, showLeft, showRight])

  // Load macro connections
  useEffect(() => {
    const loadConns = async () => {
      try {
        const resp = await fetch('/api/mirror-kg/connections?granularity_level=macro&limit=10000')
        const data = await resp.json()
        const conns: MacroConnection[] = (data.items || []).map((c: any) => ({
          id: c.id,
          source_name: (c.source_region_name_en || '').toLowerCase().trim(),
          target_name: (c.target_region_name_en || '').toLowerCase().trim(),
          confidence: c.confidence || 0.5,
          connection_type: c.connection_type || 'structural_connection',
        }))
        const state = sceneRef.current
        if (state) state.allConnections = conns
        setConnTotal(conns.length)
        setLoadedConns(conns)
      } catch (e) { console.warn('[Brain3D] Connection load failed:', e) }
    }
    loadConns()
  }, [])

  // Render connection lines
  useEffect(() => {
    const state = sceneRef.current
    if (!state) return
    state.connGroup.clear()

    if (!showConnections) { setConnCount(0); return }
    const conns = loadedConns || state.allConnections
    if (!conns || !conns.length) return

    // Build name→position map from current nodes
    const posMap = new Map<string, THREE.Vector3>()
    for (const n of nodes) {
      if (!isValidMniPoint(n.representative_point_mni)) continue
      const sp = mniToScene(n.representative_point_mni)
      posMap.set(n.name_en!.toLowerCase().trim(), new THREE.Vector3(sp.x, sp.y, sp.z))
      if (n.name_cn) posMap.set(n.name_cn.toLowerCase().trim(), new THREE.Vector3(sp.x, sp.y, sp.z))
    }

    const filtered = conns.filter(c =>
      c.confidence >= connMinConf &&
      posMap.has(c.source_name) &&
      posMap.has(c.target_name)
    )
    if (selectedNode) {
      const sName = (selectedNode.name_en || '').toLowerCase().trim()
      const filtered2 = filtered.filter(c => c.source_name === sName || c.target_name === sName)
      setConnCount(filtered2.length)
      const pts: number[] = []
      for (const c of filtered2) {
        const s = posMap.get(c.source_name)!; const t = posMap.get(c.target_name)!
        pts.push(s.x, s.y, s.z, t.x, t.y, t.z)
      }
      if (pts.length) {
        const geo = new THREE.BufferGeometry()
        geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
        const mat = new THREE.LineBasicMaterial({ color: 0x00D4FF, transparent: true, opacity: 0.7, linewidth: 1 })
        const lines = new THREE.LineSegments(geo, mat)
        state.connGroup.add(lines)
      }
    } else {
      setConnCount(filtered.length)
      const pts: number[] = []
      const colors: number[] = []
      for (const c of filtered) {
        const s = posMap.get(c.source_name)!; const t = posMap.get(c.target_name)!
        pts.push(s.x, s.y, s.z, t.x, t.y, t.z)
        // Color by confidence: high=blue, low=gray
        const color = new THREE.Color()
        color.setHSL(0.6, 0.8, 0.3 + c.confidence * 0.4)
        colors.push(color.r, color.g, color.b, color.r, color.g, color.b)
      }
      if (pts.length) {
        const geo = new THREE.BufferGeometry()
        geo.setAttribute('position', new THREE.Float32BufferAttribute(pts, 3))
        geo.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
        const mat = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.35, linewidth: 1 })
        const lines = new THREE.LineSegments(geo, mat)
        state.connGroup.add(lines)
      }
    }
  }, [nodes, showConnections, connMinConf, selectedNode, loadedConns])

  // Update node meshes when nodes/radius change
  useEffect(() => {
    const state = sceneRef.current
    if (!state || !showNodes) return

    // Remove old node meshes
    state.nodeMeshes.forEach(m => state.scene.remove(m))
    state.nodeMeshes.clear()

    const sphereGeo = new THREE.SphereGeometry(1, 16, 16)

    nodes.forEach(node => {
      if (!isValidMniPoint(node.representative_point_mni)) return
      const pos = mniToScene(node.representative_point_mni)
      const isSelected = node.region_id === selectedNode?.region_id
      const color = isSelected ? NODE_COLORS.selected : NODE_COLORS.default
      const scale = isSelected ? nodeRadius * 1.3 : nodeRadius

      const mat = new THREE.MeshPhongMaterial({ color })
      const mesh = new THREE.Mesh(sphereGeo, mat)
      mesh.position.set(pos.x, pos.y, pos.z)
      mesh.scale.setScalar(scale)
      const nodeKey = node.region_id || node.name_en || ''
      mesh.userData = { nodeId: nodeKey }
      state.scene.add(mesh)
      state.nodeMeshes.set(nodeKey, mesh)
    })
  }, [nodes, showNodes, nodeRadius, selectedNode])

  // Update node selection colors
  useEffect(() => {
    const state = sceneRef.current
    if (!state) return
    state.nodeMeshes.forEach((mesh, id) => {
      const selKey = selectedNode ? (selectedNode.region_id || selectedNode.name_en || '') : ''
      const isSelected = id === selKey
      const mat = mesh.material as THREE.MeshPhongMaterial
      mat.color.set(isSelected ? NODE_COLORS.selected : NODE_COLORS.default)
      // const scale = isSelected ? nodeRadius * 1.3 : nodeRadius
      // mesh.scale.setScalar(scale)
    })
  }, [selectedNode])

  // Update surface visibility/opacity
  useEffect(() => {
    const state = sceneRef.current
    if (!state) return
    state.surfaceGroups.left.visible = showLeft
    state.surfaceGroups.right.visible = showRight
    const updateOpacity = (group: THREE.Group) => {
      group.traverse((child: THREE.Object3D) => {
        if (child instanceof THREE.Mesh && child.material instanceof THREE.MeshPhongMaterial) {
          child.material.opacity = surfaceOpacity
        }
      })
    }
    updateOpacity(state.surfaceGroups.left)
    updateOpacity(state.surfaceGroups.right)
  }, [showLeft, showRight, surfaceOpacity])

  // View preset
  const handleViewChange = useCallback((preset: ViewPreset) => {
    setViewPreset(preset)
    const state = sceneRef.current
    if (!state) return
    const p = VIEW_PRESETS[preset]
    state.camera.position.set(...p.position)
    state.controls.target.set(...p.target)
    state.controls.update()
  }, [])

  if (initError) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', background: '#1a1a2e', color: '#f44336', flexDirection: 'column', gap: 16 }}>
        <h3>3D 渲染初始化失败</h3>
        <pre style={{ fontSize: 13 }}>{initError}</pre>
        <p style={{ color: '#888' }}>请检查浏览器是否支持 WebGL</p>
      </div>
    )
  }

  return (
    <div className="brain-3d-container">
      {/* Toolbar */}
      <div className="brain-3d-toolbar">
        <div className="brain-3d-toolbar-section">
          <label className="brain-3d-label">视角</label>
          <div className="brain-3d-btn-group">
            {(Object.keys(VIEW_NAMES) as ViewPreset[]).map((v) => (
              <button key={v}
                className={`brain-3d-btn-sm${viewPreset === v ? ' brain-3d-btn-active' : ''}`}
                onClick={() => handleViewChange(v)}>
                {VIEW_NAMES[v]}
              </button>
            ))}
          </div>
        </div>
        <div className="brain-3d-toolbar-section">
          <label className="brain-3d-label"><input type="checkbox" checked={showLeft} onChange={() => setShowLeft(!showLeft)} /> 左半球</label>
          <label className="brain-3d-label"><input type="checkbox" checked={showRight} onChange={() => setShowRight(!showRight)} /> 右半球</label>
          <label className="brain-3d-label"><input type="checkbox" checked={showNodes} onChange={() => setShowNodes(!showNodes)} /> 节点</label>
          <label className="brain-3d-label"><input type="checkbox" checked={showConnections} onChange={() => setShowConnections(!showConnections)} /> 连接 ({showConnections ? connCount : 0}/{connTotal})</label>
        </div>
        <div className="brain-3d-toolbar-section">
          <label className="brain-3d-label">透明度 <input type="range" min="0.05" max="1" step="0.05" value={surfaceOpacity} onChange={(e) => setSurfaceOpacity(parseFloat(e.target.value))} /></label>
          <label className="brain-3d-label">节点大小 <input type="range" min="0.5" max="5" step="0.1" value={nodeRadius} onChange={(e) => setNodeRadius(parseFloat(e.target.value))} /></label>
          {showConnections && <label className="brain-3d-label">置信度≥{connMinConf.toFixed(1)} <input type="range" min="0" max="1" step="0.05" value={connMinConf} onChange={(e) => setConnMinConf(parseFloat(e.target.value))} /></label>}
        </div>
      </div>

      {/* Status */}
      <div className="brain-3d-status">
        96 个脑区中 <strong>{nodes.length} 个已定位</strong>，24 个暂未绘制
        {hoveredNode && <span className="brain-3d-hover-info">{' | '}{hoveredNode.name_cn || hoveredNode.name_en} ({hoveredNode.laterality})</span>}
      </div>

      {/* Canvas container */}
      <div ref={containerRef} className="brain-3d-canvas-wrapper" style={{ flex: 1, minHeight: 300 }} />
    </div>
  )
}
