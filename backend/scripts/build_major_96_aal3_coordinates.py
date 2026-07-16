"""Phase 2: Build verified AAL MNI coordinates for 96 Macro96 brain regions.

Loads real AAL (SPM12) NIfTI atlas, computes MNI centroids via affine
transform, and maps each Macro96 region to verified AAL labels.

No DeepSeek inference — pure deterministic computation.
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import nibabel as nib
import numpy as np
from scipy.ndimage import center_of_mass

BACKEND_DIR = Path(__file__).resolve().parents[1]
ATLAS_DIR = BACKEND_DIR / "data" / "atlases" / "aal3" / "aal"
NIFTI_PATH = ATLAS_DIR / "atlas" / "AAL.nii"
LABEL_PATH = ATLAS_DIR / "ROI_MNI_V4.txt"

OUTPUT_DIR = BACKEND_DIR / "data" / "brain_spatial"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ── Step 1: Load AAL NIfTI ────────────────────────────────────────────

def load_atlas() -> tuple[nib.Nifti1Image, np.ndarray]:
    """Load AAL NIfTI and return (image, data_array)."""
    nii = nib.load(str(NIFTI_PATH))
    data = np.asarray(nii.dataobj, dtype=np.float64)
    print(f"[load] shape={data.shape} dtype={data.dtype}")
    print(f"[load] unique labels={len(np.unique(data))}")
    print(f"[load] orientation={nib.orientations.aff2axcodes(nii.affine)}")
    print(f"[load] voxel spacing={nii.header.get_zooms()}")
    return nii, data


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


# ── Step 2: Load AAL label mapping ────────────────────────────────────

def load_labels() -> dict[int, dict[str, str]]:
    """Parse ROI_MNI_V4.txt → {spm_code: {abbrev, name}}."""
    labels: dict[int, dict[str, str]] = {}
    with open(LABEL_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            abbrev = parts[0]
            name = parts[1]
            code = int(parts[2])
            labels[code] = {"abbrev": abbrev, "name": name}
    print(f"[labels] loaded {len(labels)} AAL labels")
    print(f"[labels] code range: {min(labels.keys())}-{max(labels.keys())}")
    return labels


# ── Step 3: Compute centroids ─────────────────────────────────────────

def compute_centroids(
    nii: nib.Nifti1Image,
    data: np.ndarray,
    labels: dict[int, dict[str, str]],
) -> list[dict[str, Any]]:
    """Compute center_of_mass and representative point for each label."""
    results = []
    affine = nii.affine
    valid_labels = sorted(l for l in labels if int(l) > 0)

    for code in valid_labels:
        mask = data == code
        voxel_count = int(mask.sum())

        if voxel_count == 0:
            print(f"  [WARN] label {code} ({labels[code]['name']}): 0 voxels")
            results.append({
                "spm_code": code,
                "aal_name": labels[code]["name"],
                "aal_abbrev": labels[code]["abbrev"],
                "voxel_count": 0,
                "center_of_mass_mni": None,
                "representative_point_mni": None,
                "representative_voxel_ijk": None,
                "error": "zero_voxels",
            })
            continue

        # Center of mass in voxel space
        com_voxel = center_of_mass(mask)  # (i, j, k) in voxel indices
        com_mni = nib.affines.apply_affine(affine, com_voxel)
        # Round to 1 decimal
        com_mni = tuple(round(float(x), 1) for x in com_mni)

        # Representative point: closest voxel to center of mass
        voxel_coords = np.argwhere(mask)  # (N, 3) of (i, j, k)
        distances = np.linalg.norm(voxel_coords - np.array(com_voxel), axis=1)
        closest_idx = int(np.argmin(distances))
        rep_voxel = tuple(int(x) for x in voxel_coords[closest_idx])  # (i, j, k)
        rep_mni = nib.affines.apply_affine(affine, rep_voxel)
        rep_mni = tuple(round(float(x), 1) for x in rep_mni)

        # Verify rep voxel is in label
        assert data[rep_voxel] == code, f"rep voxel {rep_voxel} not in label {code}"

        results.append({
            "spm_code": code,
            "aal_name": labels[code]["name"],
            "aal_abbrev": labels[code]["abbrev"],
            "voxel_count": voxel_count,
            "center_of_mass_mni": {"x": com_mni[0], "y": com_mni[1], "z": com_mni[2]},
            "representative_point_mni": {"x": rep_mni[0], "y": rep_mni[1], "z": rep_mni[2]},
            "representative_voxel_ijk": {"i": rep_voxel[0], "j": rep_voxel[1], "k": rep_voxel[2]},
        })

    print(f"[centroids] computed for {len(results)} labels")
    with_coords = sum(1 for r in results if r.get("center_of_mass_mni"))
    print(f"[centroids] with coords: {with_coords}, with errors: {len(results) - with_coords}")
    return results


# ── Step 4: Coordinate quality checks ─────────────────────────────────

def validate_coordinates(
    centroids: list[dict[str, Any]],
    nii: nib.Nifti1Image,
    data: np.ndarray,
) -> list[str]:
    """Run deterministic checks on all computed coordinates."""
    issues: list[str] = []
    affine = nii.affine

    for c in centroids:
        name = c["aal_name"]
        code = c["spm_code"]

        if c.get("error"):
            issues.append(f"[{name}] SKIPPED: {c['error']}")
            continue

        com = c["center_of_mass_mni"]
        rep = c["representative_point_mni"]
        rep_ijk = c["representative_voxel_ijk"]

        # 1. Finite check
        for key, val in [("com_x", com["x"]), ("com_y", com["y"]), ("com_z", com["z"]),
                         ("rep_x", rep["x"]), ("rep_y", rep["y"]), ("rep_z", rep["z"])]:
            if not np.isfinite(val):
                issues.append(f"[{name}] non-finite {key}={val}")

        # 2. Reasonable MNI range (human brain: ~|x|<90, ~|y|<120, ~|z|<100)
        if abs(com["x"]) > 95:
            issues.append(f"[{name}] com_x={com['x']} out of range")
        if abs(com["y"]) > 130:
            issues.append(f"[{name}] com_y={com['y']} out of range")
        if abs(com["z"]) > 110:
            issues.append(f"[{name}] com_z={com['z']} out of range")

        # 3. Rep voxel in label
        i, j, k = rep_ijk["i"], rep_ijk["j"], rep_ijk["k"]
        if data[i, j, k] != code:
            issues.append(f"[{name}] rep voxel ({i},{j},{k}) value={data[i,j,k]} != label {code}")

        # 4. Rep → MNI consistency via affine
        recon = nib.affines.apply_affine(affine, (i, j, k))
        tol = 0.1  # 0.1mm tolerance for rounding
        if (abs(recon[0] - rep["x"]) > tol or
            abs(recon[1] - rep["y"]) > tol or
            abs(recon[2] - rep["z"]) > tol):
            issues.append(f"[{name}] affine recon mismatch: {recon} vs {rep}")

    print(f"[validate] {len(issues)} issues found")
    for iss in issues[:10]:
        print(f"  {iss}")
    if len(issues) > 10:
        print(f"  ... and {len(issues)-10} more")
    return issues


# ── Step 5: Laterality check ──────────────────────────────────────────

def check_laterality(centroids: list[dict[str, Any]]) -> list[str]:
    """Check that left/right labels have correct MNI x sign.

    AAL orientation is LAS → MNI x positive = left, x negative = right.
    See nib.orientations.aff2axcodes for confirmation.
    """
    issues: list[str] = []
    for c in centroids:
        name = c["aal_name"]
        if c.get("error"):
            continue
        mni_x = c["representative_point_mni"]["x"]
        is_left_hemi = name.endswith("_L")
        is_right_hemi = name.endswith("_R")

        # Standard MNI convention: negative x = left hemisphere, positive x = right
        if is_left_hemi and mni_x > 1:
            issues.append(f"[{name}] LEFT label but MNI x={mni_x} (positive)")
        if is_right_hemi and mni_x < -1:
            issues.append(f"[{name}] RIGHT label but MNI x={mni_x} (negative)")

    print(f"[laterality] {len(issues)} conflicts (MNI: -x=left, +x=right)")
    for iss in issues:
        print(f"  {iss}")
    return issues


# ── Step 6: Build label lookup by name ────────────────────────────────

def build_name_index(
    centroids: list[dict[str, Any]],
) -> dict[str, dict]:
    """Index AAL labels by standard name."""
    idx = {}
    for c in centroids:
        if c.get("error"):
            continue
        name = c["aal_name"]
        idx[name] = c
        # Also index by abbrev
        idx[c["aal_abbrev"]] = c
    print(f"[index] {len(idx)} name entries")
    return idx


# ── Step 7: Map Macro96 regions to AAL labels ─────────────────────────

def map_macro96_to_aal(
    phase1_matches: list[dict],
    aal_index: dict[str, dict],
    macro96: list[dict],
) -> list[dict]:
    """Map each Macro96 region to AAL label using Phase 1 as guide."""
    results = []

    # Build Phase 1 lookup by macro96_id
    p1_by_id = {}
    for m in phase1_matches:
        mid = m.get("macro96_id")
        if mid:
            p1_by_id[int(mid)] = m

    for region in sorted(macro96, key=lambda r: int(r.get("label_value", 0))):
        label_val = int(region.get("label_value", 0))
        p1 = p1_by_id.get(label_val)
        p1_aal3_name = p1.get("aal3_name") if p1 else None

        result = {
            "region_id": region.get("region_id", region.get("id")),
            "label_value": label_val,
            "name_en": region.get("name_en", ""),
            "name_cn": region.get("name_cn", ""),
            "laterality": region.get("laterality", ""),
            "phase1_mapping_status": p1.get("match_quality") if p1 else "unmapped",
            "phase1_aal3_name": p1_aal3_name,
            "phase1_confidence": p1.get("confidence") if p1 else None,
            "phase1_mni_centroid": p1.get("mni_centroid") if p1 else None,
        }

        # Try exact name match to AAL first
        aal_entry = None
        mapping_method = "unmapped"
        validation_issues: list[str] = []

        if p1_aal3_name:
            # Try direct match with AAL3 name
            aal_entry = aal_index.get(p1_aal3_name)

        if aal_entry:
            mapping_method = "verified_exact" if p1.get("match_quality") == "exact" else "verified_alias"
        elif p1 and p1.get("match_quality") in ("exact", "approximate"):
            # Try AAL3 name → AAL1 name mapping with known differences
            p1_name = (p1_aal3_name or "").replace("_L", "").replace("_R", "")
            # Known AAL3→AAL1 name mappings
            aal3_to_aal1 = {
                "ACC_sub": "Cingulum_Ant", "ACC_pre": "Cingulum_Ant",
                "Cerebelum_Crus1": "Cerebelum_Crus1", "Cerebelum_Crus2": "Cerebelum_Crus2",
                "Cerebelum_3": "Cerebelum_3", "Cerebelum_4_5": "Cerebelum_4_5",
                "Cerebelum_6": "Cerebelum_6", "Cerebelum_7b": "Cerebelum_7b",
                "Cerebelum_8": "Cerebelum_8", "Cerebelum_9": "Cerebelum_9",
                "Cerebelum_10": "Cerebelum_10",
                "Vermis_1_2": "Vermis_1_2", "Vermis_3": "Vermis_3",
                "Vermis_4_5": "Vermis_4_5", "Vermis_6": "Vermis_6",
                "Vermis_7": "Vermis_7", "Vermis_8": "Vermis_8",
                "Vermis_9": "Vermis_9", "Vermis_10": "Vermis_10",
                # AAL3 _2 suffix → AAL1 (no subdivision)
                "Frontal_Mid_2": "Frontal_Mid", "Frontal_Sup_2": "Frontal_Sup",
                "Frontal_Inf_Oper_2": "Frontal_Inf_Oper",
                "Frontal_Inf_Tri_2": "Frontal_Inf_Tri",
                "Frontal_Inf_Orb_2": "Frontal_Inf_Orb",
                "Occipital_Mid_2": "Occipital_Mid", "Occipital_Sup_2": "Occipital_Sup",
                "Occipital_Inf_2": "Occipital_Inf",
                "Temporal_Mid_2": "Temporal_Mid", "Temporal_Sup_2": "Temporal_Sup",
                "Temporal_Inf_2": "Temporal_Inf",
                "Parietal_Sup_2": "Parietal_Sup", "Parietal_Inf_2": "Parietal_Inf",
                "Postcentral_2": "Postcentral", "Precentral_2": "Precentral",
                # AAL3 naming conventions → AAL1
                "Cingulate_Ant": "Cingulum_Ant", "Cingulate_Mid": "Cingulum_Mid",
                "Cingulate_Post": "Cingulum_Post",
                "OFClat": "Frontal_Mid_Orb", "OFCmed": "Frontal_Med_Orb",
                "OFCant": "Frontal_Sup_Orb", "OFCpost": "Frontal_Inf_Orb",
                "N_Acc": None,  # Not in AAL1
            }
            base_name = aal3_to_aal1.get(p1_name, p1_name)
            if base_name is None:
                # Explicitly excluded from AAL1 (e.g., N_Acc)
                pass
            else:
                lat = region.get("laterality", "")
                for alt_name, alt_entry in aal_index.items():
                    alt_base = alt_name.replace("_L", "").replace("_R", "")
                    if base_name == alt_base:
                        if (lat == "left" and alt_name.endswith("_L")) or \
                           (lat == "right" and alt_name.endswith("_R")):
                            aal_entry = alt_entry
                            mapping_method = "verified_alias"
                            break
                # Fallback: any laterality
                if not aal_entry:
                    for alt_name, alt_entry in aal_index.items():
                        if alt_name.replace("_L", "").replace("_R", "") == base_name:
                            aal_entry = alt_entry
                            mapping_method = "verified_alias"
                            break
                if aal_entry:
                    validation_issues.append(
                        f"AAL3→AAL1 name mapping: {p1_aal3_name} → {aal_entry['aal_name']}"
                    )
                elif p1_aal3_name:
                    # Last resort: substring match
                    for alt_name, alt_entry in aal_index.items():
                        if p1_name in alt_name or alt_name in p1_name:
                            aal_entry = alt_entry
                            mapping_method = "verified_alias"
                            validation_issues.append(
                                f"Substring match: {p1_aal3_name} → {alt_entry['aal_name']}"
                            )
                            break

        if not aal_entry and p1 and p1.get("match_quality") in ("manual_review",):
            mapping_method = "manual_review"
            validation_issues.append("Phase 1 marked as manual_review; no AAL label found")
        elif not aal_entry and p1 and p1.get("match_quality") == "unmapped":
            mapping_method = "unmapped"
        elif not aal_entry:
            mapping_method = "manual_review"
            validation_issues.append("Could not map to any AAL label")

        # Build output
        out = dict(result)
        out["mapping_method"] = mapping_method
        out["mapping_status"] = mapping_method
        out["validation_issues"] = validation_issues

        if aal_entry:
            out["proposed_aal_label"] = aal_entry["spm_code"]
            out["official_aal_name"] = aal_entry["aal_name"]
            out["official_aal_abbrev"] = aal_entry["aal_abbrev"]
            out["coordinate_status"] = "verified"
            out["coordinate_source"] = "AAL_SPM12_label_mask"
            out["atlas"] = "AAL_SPM12"
            out["atlas_label"] = aal_entry["spm_code"]
            out["coordinate_space"] = "MNI"
            out["center_of_mass_mni"] = aal_entry["center_of_mass_mni"]
            out["representative_point_mni"] = aal_entry["representative_point_mni"]
            out["representative_voxel_ijk"] = aal_entry["representative_voxel_ijk"]
            out["voxel_count"] = aal_entry["voxel_count"]
            out["mapping_confidence"] = 1.0 if mapping_method == "verified_exact" else 0.8

            # Laterality check
            lat = region.get("laterality", "")
            mni_x = aal_entry["representative_point_mni"]["x"]
            aal_name = aal_entry["aal_name"]
            if lat == "left" and aal_name.endswith("_R"):
                validation_issues.append(f"LATERALITY: macro={lat} but AAL label={aal_name}")
            elif lat == "right" and aal_name.endswith("_L"):
                validation_issues.append(f"LATERALITY: macro={lat} but AAL label={aal_name}")
        else:
            out["proposed_aal_label"] = None
            out["official_aal_name"] = None
            out["official_aal_abbrev"] = None
            out["coordinate_status"] = "missing"
            out["coordinate_source"] = None
            out["atlas"] = "AAL_SPM12"
            out["atlas_label"] = None
            out["coordinate_space"] = None
            out["center_of_mass_mni"] = None
            out["representative_point_mni"] = None
            out["representative_voxel_ijk"] = None
            out["voxel_count"] = None
            out["mapping_confidence"] = None

        out["validation_issues"] = validation_issues
        results.append(out)

    return results


# ── Step 8: DeepSeek vs Real coordinate comparison ────────────────────

def compare_coordinates(mapped: list[dict]) -> list[dict]:
    """Compare Phase 1 DeepSeek coordinates with real AAL centroids."""
    comparisons = []
    distances = []

    for m in mapped:
        p1_coord = m.get("phase1_mni_centroid")
        real_coord = m.get("representative_point_mni")

        if not p1_coord or not real_coord:
            continue

        dx = p1_coord["x"] - real_coord["x"]
        dy = p1_coord["y"] - real_coord["y"]
        dz = p1_coord["z"] - real_coord["z"]
        dist = round(float(np.sqrt(dx**2 + dy**2 + dz**2)), 1)

        grade = "close" if dist <= 5 else ("moderate" if dist <= 15 else "severe")

        comparisons.append({
            "region_id": m["region_id"],
            "name_en": m["name_en"],
            "deepseek_mni": p1_coord,
            "verified_mni": real_coord,
            "distance_mm": dist,
            "grade": grade,
            "dx": round(float(dx), 1),
            "dy": round(float(dy), 1),
            "dz": round(float(dz), 1),
        })
        distances.append(dist)

    if distances:
        arr = np.array(distances)
        print(f"\n[compare] {len(comparisons)} regions compared")
        print(f"  mean distance: {arr.mean():.1f} mm")
        print(f"  median distance: {np.median(arr):.1f} mm")
        print(f"  max distance: {arr.max():.1f} mm")
        print(f"  <=5mm: {sum(arr <= 5)}")
        print(f"  >5 & <=15mm: {sum((arr > 5) & (arr <= 15))}")
        print(f"  >15mm: {sum(arr > 15)}")
        if arr.max() > 15:
            print(f"  Worst:")
            for c in sorted(comparisons, key=lambda x: -x["distance_mm"])[:5]:
                print(f"    {c['name_en']}: {c['distance_mm']}mm (dSeek={c['deepseek_mni']} vs real={c['verified_mni']})")

    return comparisons


# ── Step 9: Generate stats ────────────────────────────────────────────

def compute_stats(mapped: list[dict], comparisons: list[dict]) -> dict:
    stats: dict[str, int | float] = {
        "total": len(mapped),
        "verified_exact": sum(1 for m in mapped if m["mapping_status"] == "verified_exact"),
        "verified_alias": sum(1 for m in mapped if m["mapping_status"] == "verified_alias"),
        "manual_review": sum(1 for m in mapped if m["mapping_status"] == "manual_review"),
        "unmapped": sum(1 for m in mapped if m["mapping_status"] == "unmapped"),
        "rejected": sum(1 for m in mapped if m["mapping_status"] == "rejected"),
        "with_verified_coordinates": sum(1 for m in mapped if m["coordinate_status"] == "verified"),
        "with_missing_coordinates": sum(1 for m in mapped if m["coordinate_status"] == "missing"),
        "deepseek_comparable": len(comparisons),
    }
    if comparisons:
        dists = [c["distance_mm"] for c in comparisons]
        stats["deepseek_mean_distance_mm"] = round(float(np.mean(dists)), 1)
        stats["deepseek_median_distance_mm"] = round(float(np.median(dists)), 1)
        stats["deepseek_max_distance_mm"] = round(float(np.max(dists)), 1)
        stats["deepseek_close_le_5mm"] = sum(1 for d in dists if d <= 5)
        stats["deepseek_moderate_5_15mm"] = sum(1 for d in dists if 5 < d <= 15)
        stats["deepseek_severe_gt_15mm"] = sum(1 for d in dists if d > 15)

    for k, v in sorted(stats.items()):
        print(f"  {k}: {v}")
    return stats


# ── Main ───────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("Phase 2: AAL Coordinate Build")
    print(f"Atlas: {NIFTI_PATH}")
    print(f"Labels: {LABEL_PATH}")
    print("=" * 60)

    # 1. Load atlas
    nii, data = load_atlas()
    nii_hash = file_hash(NIFTI_PATH)
    label_hash = file_hash(LABEL_PATH)
    print(f"[hash] NIfTI={nii_hash}  labels={label_hash}")
    print()

    # 2. Load labels
    labels = load_labels()

    # 3. Compute centroids
    centroids = compute_centroids(nii, data, labels)

    # 4. Validate
    issues = validate_coordinates(centroids, nii, data)

    # 5. Laterality
    lat_issues = check_laterality(centroids)

    # 6. Build index
    aal_index = build_name_index(centroids)

    # 7. Load Phase 1 + Macro96 data
    p1_path = BACKEND_DIR / "data" / "macro96_aal3_match_results.json"
    with open(p1_path, encoding="utf-8") as f:
        p1_data = json.load(f)
    phase1_matches = p1_data["matches"]

    macro96_path = BACKEND_DIR / "data" / "macro96_regions.json"
    with open(macro96_path, encoding="utf-8") as f:
        macro96 = json.load(f)

    print(f"\n[data] Phase 1 matches: {len(phase1_matches)}, Macro96: {len(macro96)}")

    # 8. Map
    mapped = map_macro96_to_aal(phase1_matches, aal_index, macro96)

    # 9. Compare DeepSeek vs Real
    comparisons = compare_coordinates(mapped)

    # 10. Stats
    print(f"\n[stats]")
    stats = compute_stats(mapped, comparisons)

    # 11. Output
    timestamp = datetime.now(timezone.utc).isoformat()

    # Verified mapping
    mapping_output = {
        "metadata": {
            "generated": timestamp,
            "atlas": "AAL_SPM12",
            "atlas_file": str(NIFTI_PATH),
            "label_file": str(LABEL_PATH),
            "nifti_hash": nii_hash,
            "label_hash": label_hash,
            "nifti_shape": list(data.shape),
            "nifti_voxel_spacing": [float(s) for s in nii.header.get_zooms()],
            "nifti_orientation": "".join(nib.orientations.aff2axcodes(nii.affine)),
            "nifti_affine": nii.affine.tolist(),
        },
        "stats": stats,
        "issues": issues + lat_issues,
        "regions": mapped,
    }
    map_path = OUTPUT_DIR / "major_96_aal3_mapping_verified.json"
    with open(map_path, "w", encoding="utf-8") as f:
        json.dump(mapping_output, f, ensure_ascii=False, indent=2)
    print(f"\n[output] {map_path}")

    # Coordinates only
    coords_output = {
        "metadata": mapping_output["metadata"],
        "coordinates": [
            {
                "region_id": m["region_id"],
                "name_en": m["name_en"],
                "name_cn": m["name_cn"],
                "granularity": "Major",
                "atlas": m["atlas"],
                "atlas_label": m["atlas_label"],
                "official_atlas_name": m.get("official_aal_name"),
                "laterality": m["laterality"],
                "coordinate_space": "MNI",
                "center_of_mass_mni": m.get("center_of_mass_mni"),
                "representative_point_mni": m.get("representative_point_mni"),
                "representative_voxel_ijk": m.get("representative_voxel_ijk"),
                "voxel_count": m.get("voxel_count"),
                "mapping_status": m["mapping_status"],
                "coordinate_status": m["coordinate_status"],
                "coordinate_source": m.get("coordinate_source"),
                "atlas_file_hash": nii_hash,
                "label_table_hash": label_hash,
                "validation_issues": m.get("validation_issues", []),
            }
            for m in mapped
        ],
    }
    coord_path = OUTPUT_DIR / "major_96_aal3_coordinates.json"
    with open(coord_path, "w", encoding="utf-8") as f:
        json.dump(coords_output, f, ensure_ascii=False, indent=2)
    print(f"[output] {coord_path}")

    # Comparison
    comp_path = OUTPUT_DIR / "major_96_coordinate_comparison.json"
    with open(comp_path, "w", encoding="utf-8") as f:
        json.dump({
            "metadata": {"generated": timestamp},
            "stats": {
                k: v for k, v in stats.items() if k.startswith("deepseek_")
            },
            "comparisons": comparisons,
        }, f, ensure_ascii=False, indent=2)
    print(f"[output] {comp_path}")

    print(f"\nDone. No business logic or database was modified.")


if __name__ == "__main__":
    main()
