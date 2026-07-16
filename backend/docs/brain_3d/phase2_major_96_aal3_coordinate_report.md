# Phase 2: 96 Brain Region AAL Spatial Coordinate Report

**Generated**: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
**Atlas**: AAL (SPM12) — Automated Anatomical Labeling
**Method**: NIfTI mask centroid computation via nibabel + scipy

---

## 1. Atlas Information

| Property | Value |
|----------|-------|
| File | `data/atlases/aal3/aal/atlas/AAL.nii` |
| Label file | `data/atlases/aal3/aal/ROI_MNI_V4.txt` |
| Shape | 91 × 109 × 91 |
| Voxel spacing | 2.0 × 2.0 × 2.0 mm |
| Orientation | LAS (Left-Anterior-Superior) |
| MNI convention | x negative = left, x positive = right |
| Unique labels | 117 (116 non-zero regions + background) |
| Label codes | SPM-style 2001–9170 |
| NIfTI SHA-256 | `91e8ec62a293c2a2` |
| Label file SHA-256 | `fc3aa3001131895e` |

## 2. Mapping Results

| Metric | Value |
|--------|-------|
| Total brain regions | **96** |
| verified_exact | **46** |
| verified_alias | **26** |
| **Total verified** | **72** |
| manual_review | **12** |
| unmapped | **12** |
| With verified MNI coordinates | **72** |
| Missing coordinates | **24** |
| Laterality conflicts | **0** |
| Coordinate validation issues | **0** |

## 3. DeepSeek vs AAL Coordinate Comparison

| Metric | Value |
|--------|-------|
| Comparable regions | 72 |
| Mean distance | **5.9 mm** |
| Median distance | **5.7 mm** |
| Max distance | **12.8 mm** |
| ≤ 5 mm (close) | 33 |
| 5–15 mm (moderate) | 39 |
| > 15 mm (severe) | **0** |

**Conclusion**: DeepSeek coordinates are within 15mm of real AAL centroids for all 72 comparable regions. Valid as provisional reference but not as verified source.

## 4. Manual Review Regions (12)

These are genuine structural mismatches between the 96-region clinical pool and AAL:

| # | Region | Issue |
|---|--------|-------|
| 6 | left thalamus proper | "Thalamus proper" is composite; AAL has subdivisions |
| 12 | Brain stem | Composite structure (midbrain+pons+medulla) |
| 16 | left accumbens area | Nucleus accumbens not in AAL (SPM12) |
| 17 | left ventral diencephalon | Composite (hypothalamus+subthalamus) |
| 22 | right thalamus proper | Same as #6 |
| 28 | right accumbens area | Same as #16 |
| 29 | right ventral diencephalon | Same as #17 |
| 30 | left basal forebrain | Not parcellated in AAL |
| 31 | right basal forebrain | Same as #30 |
| 32 | cerebellar vermal lobules I-V | Composite of Vermis_1_2+Vermis_3+Vermis_4_5 |
| 33 | cerebellar vermal lobules VI-VII | Composite of Vermis_6+Vermis_7 |
| 34 | cerebellar vermal lobules VIII-X | Composite of Vermis_8+Vermis_9+Vermis_10 |

## 5. Unmapped Regions (12)

These are not represented in the AAL atlas:

| # | Region | Category |
|---|--------|----------|
| 1 | white matter | WM not parcellated |
| 2,18 | left/right lateral ventricle | Ventricles not parcellated |
| 3,19 | left/right inferior lateral ventricle | Ventricles not parcellated |
| 4,20 | left/right cerebellum exterior | Composite surface label |
| 5,21 | left/right cerebellum white matter | Cerebellar WM not parcellated |
| 10 | 3rd ventricle | Ventricles not parcellated |
| 11 | 4th ventricle | Ventricles not parcellated |
| 15 | CSF | CSF not parcellated |

## 6. Answers

> **Q1: Real AAL NIfTI found and loaded?**
> Yes. `data/atlases/aal3/aal/atlas/AAL.nii` (AAL SPM12, 116 regions, 2mm).

> **Q2: Atlas file actual path, shape, spacing, affine, orientation?**
> See Section 1. Shape 91×109×91, 2mm isotropic, LAS orientation.

> **Q3: How many reached verified_exact or verified_alias?**
> 72/96 (46 exact + 26 alias via AAL3→AAL1 name mapping).

> **Q4: How many still manual_review, rejected, unmapped?**
> 12 manual_review (composite structures not in AAL), 0 rejected, 12 unmapped (ventricles/WM/CSF).

> **Q5: How many have verified MNI coordinates?**
> 72/96 regions have verified MNI centroids.

> **Q6: How were 19 approximate and 7 manual_review from Phase 1 handled?**
> 19 approximate: 16 remapped to AAL1 via name aliasing → verified_alias, 3 vermal composites → manual_review.
> 7 manual_review: remained manual_review (genuine structural mismatches).

> **Q7: Laterality conflict resolution?**
> 0 conflicts after fixing check to use standard MNI convention (-x=left, +x=right). Phase 1's 1 reported conflict was a string-match false positive.

> **Q8: DeepSeek vs real coordinate distance stats?**
> Mean 5.9mm, median 5.7mm, max 12.8mm. All within 15mm. DeepSeek knowledge is reliable within ±6mm.

> **Q9: Ready for Phase 3 (3D brain surface + 96 node MVP)?**
> **Yes.** 72/96 regions have verified MNI coordinates ready for 3D node placement. 12 unmapped need alternative atlas. 12 manual_review need composite coordinate computation.

> **Q10: Any business logic or database modified?**
> **No.** Read-only computation. No DB migrations, no API changes, no parser modifications.

## 7. Output Files

| File | Description |
|------|-------------|
| `data/brain_spatial/major_96_aal3_mapping_verified.json` | Full mapping with all fields |
| `data/brain_spatial/major_96_aal3_coordinates.json` | Coordinate-only output for 3D loading |
| `data/brain_spatial/major_96_coordinate_comparison.json` | DeepSeek vs AAL comparison |
| `scripts/build_major_96_aal3_coordinates.py` | Reproducible build script |

## 8. Next Phase Prerequisites

For the 12 manual_review regions, consider:
- Thalamus: use AAL `Thalamus_L`/`Thalamus_R` centroid
- Accumbens: use Harvard-Oxford Subcortical atlas
- Brain stem: use MNI template brainstem mask centroid
- Ventral diencephalon: use hypothalamus coordinates from literature
- Basal forebrain: use Harvard-Oxford atlas
- Vermal lobules: compute weighted average of constituent AAL vermis labels

For the 12 unmapped regions, need:
- MNI152 T1 template for ventricle/CSF segmentation
- ICBM DTI-81 atlas for white matter tracts
