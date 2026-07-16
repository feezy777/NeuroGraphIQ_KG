/**
 * brain3d.types.ts — Type definitions for the 3D brain visualization module.
 */
export interface MniPoint {
  x: number
  y: number
  z: number
}

export interface ScenePoint {
  x: number
  y: number
  z: number
}

export interface BrainRegionNode {
  region_id: string
  name_en: string
  name_cn: string
  laterality: string
  atlas_label: number | null
  mapping_status: 'verified_exact' | 'verified_alias' | 'manual_review' | 'unmapped'
  representative_point_mni: MniPoint
  center_of_mass_mni: MniPoint | null
  voxel_count: number | null
  coordinate_source: string | null
  official_atlas_name: string | null
}

export interface BrainSurfaceMesh {
  vertices: number[][] // [[x,y,z], ...]
  faces: number[][]    // [[i,j,k], ...]
}

export interface BrainSurfaceMeta {
  generated_at: string
  atlas: string
  atlas_version: string
  coordinate_space: string
  hemispheres: {
    left: { file: string; vertex_count: number; face_count: number; split_rule: string }
    right: { file: string; vertex_count: number; face_count: number; split_rule: string }
  }
  atlas_info: {
    name: string
    reference: string
    shape: number[]
    spacing_mm: number[]
    orientation: string
    n_labels: number
  }
}

export interface BrainRegionNodesData {
  metadata: {
    generated_at: string
    total_regions: number
    plotted_nodes: number
    coordinate_space: string
    atlas: string
    atlas_version: string
  }
  nodes: BrainRegionNode[]
}

export type ViewPreset =
  | 'left-lateral'
  | 'right-lateral'
  | 'anterior'
  | 'posterior'
  | 'superior'
  | 'inferior'
  | 'default'
