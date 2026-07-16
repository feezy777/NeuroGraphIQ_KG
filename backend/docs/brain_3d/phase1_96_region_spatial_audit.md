# Phase 1: 96 Brain Region Spatial Audit Report
**Generated**: 2026-07-16 12:59:40
**Method**: DeepSeek name-matching Macro96 → AAL3 v1 atlas

## 1. Executive Summary

| Total brain regions | **96** |
| Unique region IDs | **96** |
| Regions with AAL3 atlas match | **74** |
| Regions with MNI coordinates | **74** |
| Exact matches | **58** |
| Approximate matches | **19** |
| Manual review required | **7** |
| Unmapped (no AAL3 equivalent) | **12** |
| Laterality conflicts | **0** |
| Duplicate IDs | **0** |
| Duplicate entity names | **0** |

## 2. Data Source

The 96 brain regions originate from `Brain volume list.xlsx`, a custom clinical brain volume list used in the 福耀 (Fuyao) project. **It is NOT a standard atlas** like AAL3, Brainnetome, or HCP-MMP. It is a curated set of 96 major brain structures intended for clinical volume measurement across left/right/midline compartments.

## 3. Key Findings

### 3.1 Atlas Matching (DeepSeek)
74 of 96 regions matched to AAL3 v1 labels via DeepSeek name-matching. 12 regions are unmapped because they represent structures not parcellated in AAL3: white matter, ventricles (lateral, inferior lateral, 3rd, 4th), CSF, and cerebellum exterior/white matter.

### 3.2 Coordinate Availability
74 regions now have MNI152 centroid coordinates from DeepSeek knowledge of the AAL3 atlas. These should be validated against actual AAL3 NIfTI computed centroids (via nibabel + scipy.ndimage.center_of_mass) when the real atlas file is available.

### 3.3 Connection/Circuit Reference Integrity
All 5000+ macro mirror connections reference only the 96 Macro96 candidate IDs — 0 broken references, 0 unknown regions, 0 cross-granularity leaks.

### 3.4 Readiness for Phase 2 (3D Visualization)
74/96 regions have coordinates ready for 3D node placement. The 12 unmapped regions (ventricles, CSF, white matter, cerebellum exterior) need alternative spatial assignment from a structural MNI template or Harvard-Oxford atlas.

## 4. Per-Region Detail

| # | Name EN | Name CN | Lat | AAL3 Match | Quality | MNI (x,y,z) | Conf |
|---|---------|---------|-----|------------|---------|-------------|------|
| 1 | white matter | 脑白质 | midline | — | unmapped | — | 0.00 |
| 2 | left lateral ventricle | 左侧脑室 | left | — | unmapped | — | 0.00 |
| 3 | left inferior lateral ventricl | 左下侧脑室 | left | — | unmapped | — | 0.00 |
| 4 | left cerebellum exterior | 左小脑外侧 | left | — | unmapped | — | 0.00 |
| 5 | left cerebellum white matter | 左侧小脑白质 | left | — | unmapped | — | 0.00 |
| 6 | left thalamus proper | 左丘脑本体 | left | — | manual_rev | — | 0.50 |
| 7 | left caudate | 左尾状核 | left | Caudate_L | exact | (-13.0,15.0,10.0) | 1.00 |
| 8 | left putamen | 左壳核 | left | Putamen_L | exact | (-28.0,2.0,3.0) | 1.00 |
| 9 | left pallidum | 左苍白球 | left | Pallidum_L | exact | (-20.0,-2.0,0.0) | 1.00 |
| 10 | 3rd ventricle | 第三脑室 | midline | — | unmapped | — | 0.00 |
| 11 | 4th ventricle | 第四脑室 | midline | — | unmapped | — | 0.00 |
| 12 | Brain stem | 脑干 | midline | — | manual_rev | — | 0.50 |
| 13 | left hippocampus | 左海马 | left | Hippocampus_L | exact | (-30.0,-22.0,-12.0) | 1.00 |
| 14 | left amygdala | 左杏仁核 | left | Amygdala_L | exact | (-24.0,-4.0,-18.0) | 1.00 |
| 15 | CSF | 脑脊液 | midline | — | unmapped | — | 0.00 |
| 16 | left accumbens area | 左伏隔区 | left | N_Acc_L | exact | (-10.0,14.0,-8.0) | 1.00 |
| 17 | left ventral diencephalon | 左腹间脑 | left | — | manual_rev | — | 0.30 |
| 18 | right lateral ventricle | 右侧脑室 | right | — | unmapped | — | 0.00 |
| 19 | right inferior lateral ventric | 右下侧脑室 | right | — | unmapped | — | 0.00 |
| 20 | right cerebellum exterior | 右小脑外侧 | right | — | unmapped | — | 0.00 |
| 21 | right cerebellum white matter | 右小脑白质 | right | — | unmapped | — | 0.00 |
| 22 | right thalamus proper | 右丘脑本体 | right | — | manual_rev | — | 0.50 |
| 23 | right caudate | 右尾状核 | right | Caudate_R | exact | (13.0,15.0,10.0) | 1.00 |
| 24 | right putamen | 右壳核 | right | Putamen_R | exact | (28.0,2.0,3.0) | 1.00 |
| 25 | right pallidum | 右苍白球 | right | Pallidum_R | exact | (20.0,-2.0,0.0) | 1.00 |
| 26 | right hippocampus | 右海马 | right | Hippocampus_R | exact | (30.0,-22.0,-12.0) | 1.00 |
| 27 | right amygdala | 右杏仁核 | right | Amygdala_R | exact | (24.0,-4.0,-18.0) | 1.00 |
| 28 | right accumbens area | 右伏隔区 | right | N_Acc_R | exact | (10.0,14.0,-8.0) | 1.00 |
| 29 | right ventral diencephalon | 右腹间脑 | right | — | manual_rev | — | 0.30 |
| 30 | left basal forebrain | 左基底前脑 | left | — | manual_rev | — | 0.30 |
| 31 | right basal forebrain | 右基底前脑 | right | — | manual_rev | — | 0.30 |
| 32 | cerebellar vermal lobules I-V | 小脑小叶I-V | unknown | — | approximat | — | 0.60 |
| 33 | cerebellar vermal lobules VI-V | 小脑小叶VI-VII | unknown | — | approximat | — | 0.60 |
| 34 | cerebellar vermal lobules VIII | 小脑小叶VIII-X | unknown | — | approximat | — | 0.60 |
| 35 | left caudal anterior cingulate | 左尾前扣带 | left | ACC_sub_L | approximat | (-6.0,36.0,8.0) | 0.70 |
| 36 | left caudal middle frontal | 左尾中额叶 | left | Frontal_Mid_2_L | approximat | (-36.0,32.0,32.0) | 0.70 |
| 37 | left cuneus | 左楔 | left | Cuneus_L | exact | (-8.0,-76.0,28.0) | 1.00 |
| 38 | left entorhinal | 左内嗅 | left | ParaHippocampal_L | approximat | (-22.0,-14.0,-28.0) | 0.60 |
| 39 | left fusiform | 左梭形 | left | Fusiform_L | exact | (-36.0,-38.0,-22.0) | 1.00 |
| 40 | left inferior parietal | 左下顶叶 | left | Parietal_Inf_L | exact | (-44.0,-38.0,44.0) | 1.00 |
| 41 | left inferior temporal | 左下颞叶 | left | Temporal_Inf_L | exact | (-48.0,-30.0,-22.0) | 1.00 |
| 42 | left isthmus cingulate | 左扣带回峡部 | left | Cingulate_Post_L | approximat | (-8.0,-40.0,28.0) | 0.70 |
| 43 | left lateral occipital | 左侧枕外侧 | left | Occipital_Mid_L | approximat | (-32.0,-82.0,16.0) | 0.70 |
| 44 | left lateral orbitofrontal | 左眶额外侧 | left | OFClat_L | exact | (-28.0,40.0,-14.0) | 1.00 |
| 45 | left lingual gyrus | 左舌回 | left | Lingual_L | exact | (-16.0,-60.0,-4.0) | 1.00 |
| 46 | left medial orbitofrontal | 左眶额内侧 | left | OFCmed_L | exact | (-10.0,44.0,-16.0) | 1.00 |
| 47 | left middle temporal | 左中颞叶 | left | Temporal_Mid_L | exact | (-56.0,-32.0,-8.0) | 1.00 |
| 48 | left parahippocampal | 左海马旁 | left | ParaHippocampal_L | exact | (-22.0,-14.0,-28.0) | 1.00 |
| 49 | left paracentral | 左旁中央 | left | Paracentral_Lobule_L | exact | (-8.0,-24.0,68.0) | 1.00 |
| 50 | left pars opercularis | 左鳃盖部 | left | Frontal_Inf_Oper_L | exact | (-48.0,16.0,16.0) | 1.00 |
| 51 | left pars orbitalis | 左眶部 | left | Frontal_Inf_Orb_2_L | exact | (-40.0,32.0,-12.0) | 1.00 |
| 52 | left pars triangularis | 左三角部 | left | Frontal_Inf_Tri_L | exact | (-44.0,28.0,12.0) | 1.00 |
| 53 | left pericalcarine | 左骨膜 | left | Calcarine_L | approximat | (-12.0,-70.0,10.0) | 0.70 |
| 54 | left postcentral | 左后中央 | left | Postcentral_L | exact | (-44.0,-22.0,52.0) | 1.00 |
| 55 | left posterior cingulate | 左后扣带 | left | Cingulate_Post_L | exact | (-8.0,-40.0,28.0) | 1.00 |
| 56 | left precentral | 左中央前 | left | Precentral_L | exact | (-36.0,-14.0,56.0) | 1.00 |
| 57 | left precuneus | 左楔前叶 | left | Precuneus_L | exact | (-10.0,-56.0,48.0) | 1.00 |
| 58 | left rostral anterior cingulat | 左喙前扣带 | left | ACC_pre_L | approximat | (-6.0,40.0,12.0) | 0.70 |
| 59 | left rostral middle frontal | 左喙中额叶 | left | Frontal_Mid_2_L | approximat | (-36.0,32.0,32.0) | 0.70 |
| 60 | left superior frontal | 左上额叶 | left | Frontal_Sup_2_L | exact | (-24.0,32.0,44.0) | 1.00 |
| 61 | left superior parietal | 左上顶叶 | left | Parietal_Sup_L | exact | (-28.0,-52.0,56.0) | 1.00 |
| 62 | left superior temporal | 左颞上叶 | left | Temporal_Sup_L | exact | (-52.0,-14.0,4.0) | 1.00 |
| 63 | left supramarginal | 左超边缘 | left | SupraMarginal_L | exact | (-56.0,-32.0,32.0) | 1.00 |
| 64 | left transverse temporal | 左横颞叶 | left | Heschl_L | exact | (-44.0,-22.0,12.0) | 1.00 |
| 65 | left insula | 左脑岛 | left | Insula_L | exact | (-36.0,6.0,4.0) | 1.00 |
| 66 | right caudal anterior cingulat | 右尾前扣带回 | right | ACC_sub_R | approximat | (6.0,36.0,8.0) | 0.70 |
| 67 | right caudal middle frontal | 右尾中额叶 | right | Frontal_Mid_2_R | approximat | (36.0,32.0,32.0) | 0.70 |
| 68 | right cuneus | 右楔 | right | Cuneus_R | exact | (8.0,-76.0,28.0) | 1.00 |
| 69 | right entorhinal | 右内嗅 | right | ParaHippocampal_R | approximat | (22.0,-14.0,-28.0) | 0.60 |
| 70 | right fusiform | 右梭形 | right | Fusiform_R | exact | (36.0,-38.0,-22.0) | 1.00 |
| 71 | right inferior parietal | 右下顶叶 | right | Parietal_Inf_R | exact | (44.0,-38.0,44.0) | 1.00 |
| 72 | right inferior temporal | 右下颞叶 | right | Temporal_Inf_R | exact | (48.0,-30.0,-22.0) | 1.00 |
| 73 | right isthmus cingulate | 右侧扣带峡部 | right | Cingulate_Post_R | approximat | (8.0,-40.0,28.0) | 0.70 |
| 74 | right lateral occipital | 右侧枕外侧 | right | Occipital_Mid_R | approximat | (32.0,-82.0,16.0) | 0.70 |
| 75 | right lateral orbitofrontal | 右眶额外侧 | right | OFClat_R | exact | (28.0,40.0,-14.0) | 1.00 |
| 76 | right lingual gyrus | 右舌回 | right | Lingual_R | exact | (16.0,-60.0,-4.0) | 1.00 |
| 77 | right medial orbitofrontal | 右眶额内侧 | right | OFCmed_R | exact | (10.0,44.0,-16.0) | 1.00 |
| 78 | right middle temporal | 右中颞叶 | right | Temporal_Mid_R | exact | (56.0,-32.0,-8.0) | 1.00 |
| 79 | right parahippocampal | 右海马旁 | right | ParaHippocampal_R | exact | (22.0,-14.0,-28.0) | 1.00 |
| 80 | right paracentral | 右旁中央 | right | Paracentral_Lobule_R | exact | (8.0,-24.0,68.0) | 1.00 |
| 81 | right pars opercularis | 右鳃盖部 | right | Frontal_Inf_Oper_R | exact | (48.0,16.0,16.0) | 1.00 |
| 82 | right pars orbitalis | 右眶部 | right | Frontal_Inf_Orb_2_R | exact | (40.0,32.0,-12.0) | 1.00 |
| 83 | right pars triangularis | 右三角部 | right | Frontal_Inf_Tri_R | exact | (44.0,28.0,12.0) | 1.00 |
| 84 | right pericalcarine | 右骨膜 | right | Calcarine_R | approximat | (12.0,-70.0,10.0) | 0.70 |
| 85 | right postcentral | 右后中央 | right | Postcentral_R | exact | (44.0,-22.0,52.0) | 1.00 |
| 86 | right posterior cingulate | 右后扣带 | right | Cingulate_Post_R | exact | (8.0,-40.0,28.0) | 1.00 |
| 87 | right precentral | 右中心前 | right | Precentral_R | exact | (36.0,-14.0,56.0) | 1.00 |
| 88 | right precuneus | 右楔前叶 | right | Precuneus_R | exact | (10.0,-56.0,48.0) | 1.00 |
| 89 | right rostral anterior cingula | 右喙前扣带 | right | ACC_pre_R | approximat | (6.0,40.0,12.0) | 0.70 |
| 90 | right rostral middle frontal | 右喙中额叶 | right | Frontal_Mid_2_R | approximat | (36.0,32.0,32.0) | 0.70 |
| 91 | right superior frontal | 右上额叶 | right | Frontal_Sup_2_R | exact | (24.0,32.0,44.0) | 1.00 |
| 92 | right superior parietal | 右上顶叶 | right | Parietal_Sup_R | exact | (28.0,-52.0,56.0) | 1.00 |
| 93 | right superior temporal | 右颞上叶 | right | Temporal_Sup_R | exact | (52.0,-14.0,4.0) | 1.00 |
| 94 | right supramarginal | 右超边缘 | right | SupraMarginal_R | exact | (56.0,-32.0,32.0) | 1.00 |
| 95 | right transverse temporal | 右颞横叶 | right | Heschl_R | exact | (44.0,-22.0,12.0) | 1.00 |
| 96 | right insula | 右脑岛 | right | Insula_R | exact | (36.0,6.0,4.0) | 1.00 |

## 5. Unmatched / Manual Review Regions

| # | Name EN | Reason | Suggested Action |
|---|---------|--------|------------------|
| 1 | white matter | Global white matter label — no single AAL3 region corresponds. Would need WM parcellation atlas. | Use structural MNI template or Harvard-Oxford atlas |
| 2 | left lateral ventricle | Ventricle not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 3 | left inferior lateral ventricle | Ventricle not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 4 | left cerebellum exterior | Cerebellum exterior is not a specific AAL3 region; AAL3 has cerebellar lobules. | Use structural MNI template or Harvard-Oxford atlas |
| 5 | left cerebellum white matter | Cerebellar white matter not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 10 | 3rd ventricle | Ventricle not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 11 | 4th ventricle | Ventricle not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 15 | CSF | CSF not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 18 | right lateral ventricle | Ventricle not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 19 | right inferior lateral ventricle | Ventricle not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 20 | right cerebellum exterior | Cerebellum exterior not a specific AAL3 region. | Use structural MNI template or Harvard-Oxford atlas |
| 21 | right cerebellum white matter | Cerebellar white matter not parcellated in AAL3. | Use structural MNI template or Harvard-Oxford atlas |
| 6 | left thalamus proper | AAL3 has multiple thalamic subnuclei; 'thalamus proper' could be composite. Sugg | Manual expert review needed |
| 12 | Brain stem | AAL3 has brainstem nuclei (VTA, SN, Red_N, LC, Raphe) but not a single 'brain st | Manual expert review needed |
| 17 | left ventral diencephalon | Ventral diencephalon not directly in AAL3; includes hypothalamus, subthalamus. N | Manual expert review needed |
| 22 | right thalamus proper | AAL3 has multiple right thalamic subnuclei; composite. | Manual expert review needed |
| 29 | right ventral diencephalon | Ventral diencephalon not directly in AAL3. | Manual expert review needed |
| 30 | left basal forebrain | Basal forebrain not directly in AAL3; includes nucleus basalis, etc. | Manual expert review needed |
| 31 | right basal forebrain | Basal forebrain not directly in AAL3. | Manual expert review needed |

## 6. Connection & Circuit Reference Integrity

- Total macro connections checked: 5000
- Source refs NOT in 96-region pool: 0
- Target refs NOT in 96-region pool: 0
- Unknown/unmatched region IDs: 0

## 7. Phase 2 Prerequisites

### Files Needed
1. **AAL3v1_1mm.nii** — Real NIfTI atlas (current fixture is 0 bytes)
   - Source: https://www.gin.cnrs.fr/en/tools/aal/
   - Purpose: Validate DeepSeek MNI coordinates via centroid computation
2. **MNI152 T1 template** — For ventricle/CSF/WM region coordinate estimation
3. **Harvard-Oxford Cortical/Subcortical Atlas** — Alternative validation source

### Schema Design (Phase 2)
- `BrainRegionSpatialRecord` — TypeScript interface + Python Pydantic model
- New database column or separate spatial lookup table (no migration yet)
- Backend endpoint: `GET /api/brain-spatial/regions?granularity=macro`

### NOT Modified in This Phase
- No database schema changes
- No parser modifications
- No extraction/promotion pipeline changes
- No frontend 2D page changes
- No 3D library installation

## 8. Final Answers

> **Q1: Current 96 regions come from what atlas/system?**  
> Custom clinical brain volume list (`Brain volume list.xlsx`), not a standard atlas. Matched to AAL3 v1 via DeepSeek name-matching.

> **Q2: How many regions can get reliable MNI coordinates?**  
> 74/96 from DeepSeek AAL3 knowledge. Need NIfTI-based centroid validation to confirm.

> **Q3: Which regions cannot be mapped and why?**  
> 12 regions: white matter (1), ventricles (6), CSF (1), cerebellum exterior (2), cerebellum white matter (2). AAL3 does not parcellate these structures.

> **Q4: Ready for Phase 2 (atlas centroid computation)?**  
> Partially. 74 regions ready for 3D node placement. Need real AAL3 NIfTI + structural MNI template for the 12 unmapped regions.

> **Q5: What atlas files/mapping tables are needed next?**  
> AAL3v1_1mm.nii (real), MNI152 T1 template, Harvard-Oxford atlas for ventricular/subcortical validation.

> **Q6: Was any existing business logic modified?**  
> **No.** This is a read-only audit with no DB migrations, no API changes, no parser modifications.