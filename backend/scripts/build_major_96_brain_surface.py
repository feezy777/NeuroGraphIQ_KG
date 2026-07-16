"""Phase 3: Build standard brain surface from AAL atlas mask.

Uses marching cubes on the non-zero label union mask to generate
left/right hemisphere GLB surface meshes in MNI space.
"""
from __future__ import annotations

import json
import hashlib
from datetime import datetime, timezone
from pathlib import Path

import nibabel as nib
import numpy as np
from scipy.ndimage import binary_fill_holes, binary_closing, gaussian_filter

BACKEND_DIR = Path(__file__).resolve().parents[1]
ATLAS_NIFTI = BACKEND_DIR / "data" / "atlases" / "aal3" / "aal" / "atlas" / "AAL.nii"
OUTPUT_DIR = BACKEND_DIR.parent / "frontend" / "public" / "brain_3d" / "major96"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Step 1: Load atlas and create brain mask ──────────────────────────

def load_atlas():
    nii = nib.load(str(ATLAS_NIFTI))
    data = np.asarray(nii.dataobj, dtype=np.float64)
    return nii, data


def create_masks(data: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Create whole brain, left hemisphere, right hemisphere masks."""
    # Whole brain: all non-zero labels
    brain_mask = data > 0

    # Close small gaps
    brain_mask = binary_closing(brain_mask, structure=np.ones((2, 2, 2)), iterations=1)
    brain_mask = binary_fill_holes(brain_mask)

    # Split left/right by MNI x=0 plane
    # Get MNI x coordinate for each voxel
    # MNI x = affine[0,0] * i + affine[0,3]
    # At MNI x=0: i = -affine[0,3] / affine[0,0]
    # With affine [[-2,0,0,90], [0,2,0,-126], [0,0,2,-72], [0,0,0,1]]
    # x = -2*i + 90 → i = (90 - x) / 2 → at x=0, i=45
    # So voxels with i > 45 have MNI x < 0 (left)
    # Voxels with i < 45 have MNI x > 0 (right)

    # Use the affine to find the midline voxel index
    affine = nib.load(str(ATLAS_NIFTI)).affine
    n_i = data.shape[0]
    # Compute MNI x for all voxel i indices
    i_indices = np.arange(n_i)
    mni_x_values = affine[0, 0] * i_indices + affine[0, 3]
    # left: MNI x < 0
    left_voxels = mni_x_values < 0
    right_voxels = mni_x_values >= 0

    left_mask = np.zeros_like(brain_mask)
    right_mask = np.zeros_like(brain_mask)
    left_mask[left_voxels, :, :] = brain_mask[left_voxels, :, :]
    right_mask[right_voxels, :, :] = brain_mask[right_voxels, :, :]

    print(f"Brain mask: {brain_mask.sum():,} voxels")
    print(f"Left hem: {left_mask.sum():,} voxels")
    print(f"Right hem: {right_mask.sum():,} voxels")
    return brain_mask, left_mask, right_mask


# ── Step 2: Generate surface via marching cubes ───────────────────────

def marching_cubes_surface(
    mask: np.ndarray, affine: np.ndarray, level: float = 0.5, step: int = 1
) -> tuple[np.ndarray, np.ndarray]:
    """Generate mesh from binary mask using skimage marching_cubes."""
    from skimage.measure import marching_cubes as mc

    # Optionally downsample for performance
    if step > 1:
        mask = mask[::step, ::step, ::step]
        # Adjust affine for downsampling
        scale = np.diag([step, step, step, 1.0])
        affine = affine @ scale

    verts, faces, normals, values = mc(mask.astype(np.float32), level=level)

    # Marching cubes returns vertices in voxel index space (i, j, k)
    # Convert to MNI world coordinates via affine
    # skimage marching cubes uses (z, y, x) ordering by default? Check.
    # skimage.measure.marching_cubes returns verts in (row, col, slice) = (i, j, k)
    # This matches nibabel voxel indexing
    verts_mni = nib.affines.apply_affine(affine, verts)

    return verts_mni.astype(np.float32), faces.astype(np.uint32)


# ── Step 3: Smooth and simplify ──────────────────────────────────────

def smooth_mesh(verts: np.ndarray, faces: np.ndarray, iterations: int = 3) -> np.ndarray:
    """Simple Laplacian smoothing."""
    for _ in range(iterations):
        new_verts = verts.copy()
        for i in range(len(verts)):
            # Find neighbors
            neighbor_mask = np.any(faces == i, axis=1)
            neighbor_faces = faces[neighbor_mask]
            neighbors = np.setdiff1d(neighbor_faces.ravel(), [i])
            if len(neighbors) > 0:
                new_verts[i] = verts[neighbors].mean(axis=0)
        # Blend: 50% original, 50% smoothed
        verts = verts * 0.5 + new_verts * 0.5
    return verts


def simplify_mesh(verts: np.ndarray, faces: np.ndarray, target_faces: int = 20000) -> tuple[np.ndarray, np.ndarray]:
    """Reduce face count using fast_simplification if available."""
    try:
        from fast_simplification import simplify
        if len(faces) > target_faces:
            verts_simp, faces_simp = simplify(verts, faces, target_count=target_faces)
            return verts_simp, faces_simp
    except ImportError:
        pass
    # If faces already low enough, return as-is
    if len(faces) <= target_faces:
        return verts, faces
    # Simple decimation: keep every Nth face
    keep = max(1, len(faces) // target_faces)
    return verts, faces[::keep]


# ── Step 4: Export as JSON (Three.js compatible) ─────────────────────

def export_mesh_json(
    verts: np.ndarray,
    faces: np.ndarray,
    name: str,
    metadata: dict,
):
    """Export mesh as JSON with vertex positions and face indices."""
    data = {
        "metadata": metadata,
        "vertices": verts.tolist(),
        "faces": faces.tolist(),
        "vertex_count": len(verts),
        "face_count": len(faces),
    }
    path = OUTPUT_DIR / f"{name}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)
    print(f"Exported {name}: {len(verts)} verts, {len(faces)} faces → {path}")
    return path


# ── Step 5: Export node coordinates ──────────────────────────────────

def export_nodes(coordinates_file: Path):
    """Copy and filter coordinate JSON for frontend consumption."""
    with open(coordinates_file, encoding="utf-8") as f:
        data = json.load(f)

    # Filter: only verified_exact + verified_alias
    nodes = []
    for c in data["coordinates"]:
        if c.get("coordinate_status") == "verified" and c.get("mapping_status") in (
            "verified_exact",
            "verified_alias",
        ):
            rp = c.get("representative_point_mni")
            if rp and all(np.isfinite([rp["x"], rp["y"], rp["z"]])):
                nodes.append({
                    "region_id": c["region_id"],
                    "name_en": c["name_en"],
                    "name_cn": c["name_cn"],
                    "laterality": c["laterality"],
                    "atlas_label": c.get("atlas_label"),
                    "mapping_status": c["mapping_status"],
                    "representative_point_mni": rp,
                    "center_of_mass_mni": c.get("center_of_mass_mni"),
                    "voxel_count": c.get("voxel_count"),
                    "coordinate_source": c.get("coordinate_source"),
                    "official_atlas_name": c.get("official_atlas_name"),
                })

    node_path = OUTPUT_DIR / "brain_region_nodes.json"
    with open(node_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "total_regions": len(data["coordinates"]),
                "plotted_nodes": len(nodes),
                "coordinate_space": "MNI",
                "atlas": data["metadata"]["atlas"],
                "atlas_version": data["metadata"].get("atlas_version", ""),
            },
            "nodes": nodes,
        }, f, ensure_ascii=False, indent=2)
    print(f"Exported {len(nodes)} nodes → {node_path}")
    return node_path


# ── Main ─────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 3: Brain Surface Generation")
    print(f"Atlas: {ATLAS_NIFTI}")
    print("=" * 60)

    # Load
    nii, data = load_atlas()
    affine = nii.affine
    shape = data.shape
    spacing = nii.header.get_zooms()
    orientation = "".join(nib.orientations.aff2axcodes(affine))
    nii_hash = hashlib.sha256(ATLAS_NIFTI.read_bytes()).hexdigest()[:16]

    print(f"[atlas] shape={shape} spacing={spacing} orientation={orientation}")
    print(f"[atlas] hash={nii_hash}")

    # Create masks
    brain_mask, left_mask, right_mask = create_masks(data)

    # Generate surfaces (with step=2 for 2mm data → 4mm effective to reduce face count)
    timestamp = datetime.now(timezone.utc).isoformat()
    metadata_base = {
        "source_atlas_path": str(ATLAS_NIFTI),
        "source_atlas_hash": nii_hash,
        "source_template_path": str(ATLAS_NIFTI),
        "surface_generation_method": "marching_cubes_on_atlas_label_union",
        "source_shape": list(shape),
        "spacing": [float(s) for s in spacing],
        "affine": affine.tolist(),
        "axis_codes": orientation,
        "coordinate_space": "MNI",
        "generated_at": timestamp,
        "downsample_step": 1,
    }

    # Generate left surface
    print("\n[surface] generating left hemisphere...")
    verts_left, faces_left = marching_cubes_surface(left_mask, affine, step=1)
    verts_left = smooth_mesh(verts_left, faces_left, iterations=2)
    verts_left, faces_left = simplify_mesh(verts_left, faces_left, target_faces=15000)
    left_meta = {
        **metadata_base,
        "hemisphere": "left",
        "split_rule": "MNI x < 0",
        "mesh_coordinate_convention": "MNI_world_RAS",
    }
    export_mesh_json(verts_left, faces_left, "brain_left", left_meta)

    # Generate right surface
    print("\n[surface] generating right hemisphere...")
    verts_right, faces_right = marching_cubes_surface(right_mask, affine, step=1)
    verts_right = smooth_mesh(verts_right, faces_right, iterations=2)
    verts_right, faces_right = simplify_mesh(verts_right, faces_right, target_faces=15000)
    right_meta = {
        **metadata_base,
        "hemisphere": "right",
        "split_rule": "MNI x >= 0",
        "mesh_coordinate_convention": "MNI_world_RAS",
    }
    export_mesh_json(verts_right, faces_right, "brain_right", right_meta)

    # Export surface metadata
    surface_meta = {
        "generated_at": timestamp,
        "atlas": "AAL",
        "atlas_version": "Tzourio-Mazoyer_2002",
        "coordinate_space": "MNI",
        "hemispheres": {
            "left": {
                "file": "brain_left.json",
                "vertex_count": len(verts_left),
                "face_count": len(faces_left),
                "split_rule": "MNI x < 0",
            },
            "right": {
                "file": "brain_right.json",
                "vertex_count": len(verts_right),
                "face_count": len(faces_right),
                "split_rule": "MNI x >= 0",
            },
        },
        "atlas_info": {
            "name": "AAL",
            "reference": "Tzourio-Mazoyer et al., NeuroImage 2002",
            "shape": list(shape),
            "spacing_mm": [float(s) for s in spacing],
            "orientation": orientation,
            "n_labels": 116,
        },
    }
    meta_path = OUTPUT_DIR / "brain_surface_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(surface_meta, f, ensure_ascii=False, indent=2)
    print(f"\n[meta] {meta_path}")

    # Export nodes
    coord_file = BACKEND_DIR / "data" / "brain_spatial" / "major_96_aal3_coordinates.json"
    export_nodes(coord_file)

    print(f"\nDone. Output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()
