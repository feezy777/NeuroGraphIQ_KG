/**
 * mniSceneTransform.ts — Deterministic MNI ↔ Three.js scene coordinate transform.
 *
 * MNI convention:  x=left→right+, y=posterior→anterior+, z=inferior→superior+
 * Three.js scene:  X=MNI_x, Y=MNI_z, Z=-MNI_y
 *
 * This is the ONE AND ONLY transform used by all brain-3d components.
 */
import type { MniPoint, ScenePoint } from './brain3d.types'

/** MNI world (mm) → Three.js scene coordinates */
export function mniToScene(mni: MniPoint): ScenePoint {
  return {
    x: mni.x,
    y: mni.z,
    z: -mni.y,
  }
}

/** Three.js scene → MNI world (mm) — inverse of mniToScene */
export function sceneToMni(scene: ScenePoint): MniPoint {
  return {
    x: scene.x,
    y: -scene.z,
    z: scene.y,
  }
}

/** Validate that a point has all finite numeric values */
export function isValidMniPoint(p: MniPoint | null | undefined): p is MniPoint {
  if (!p) return false
  return Number.isFinite(p.x) && Number.isFinite(p.y) && Number.isFinite(p.z)
}

/** Check round-trip: mni→scene→mni preserves the original */
export function verifyRoundTrip(mni: MniPoint, tolerance = 0.001): boolean {
  const scene = mniToScene(mni)
  const back = sceneToMni(scene)
  return (
    Math.abs(back.x - mni.x) < tolerance &&
    Math.abs(back.y - mni.y) < tolerance &&
    Math.abs(back.z - mni.z) < tolerance
  )
}
