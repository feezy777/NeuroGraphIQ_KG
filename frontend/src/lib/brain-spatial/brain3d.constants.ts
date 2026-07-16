/**
 * brain3d.constants.ts — 3D visualization constants.
 */
import type { ViewPreset } from './brain3d.types'

export const VIEW_PRESETS: Record<ViewPreset, { position: [number, number, number]; target: [number, number, number] }> = {
  default:       { position: [0, 0, 200],  target: [0, 0, 0] },
  'left-lateral': { position: [-200, 0, 0], target: [0, 0, 0] },
  'right-lateral':{ position: [200, 0, 0],  target: [0, 0, 0] },
  anterior:      { position: [0, 200, 0],  target: [0, 0, 0] },
  posterior:     { position: [0, -200, 0], target: [0, 0, 0] },
  superior:      { position: [0, 0, 200],  target: [0, 0, 0] },
  inferior:      { position: [0, 0, -200], target: [0, 0, 0] },
}

export const NODE_COLORS = {
  default: '#4A90D9',
  hover: '#6DB3F2',
  selected: '#00D4FF',
  selectedRing: '#00D4FF',
}

export const BRAIN_SURFACE_COLOR = '#C8C8C8'
export const BRAIN_SURFACE_OPACITY_DEFAULT = 0.28
