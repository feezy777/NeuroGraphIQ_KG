-- Formal / production coarse-grain schema (separate DB: neurographiq_kg_v3_candidate).
-- Isomorphic to workbench coarse_* tables; final_* prefix avoids cross-DB name clash.

CREATE TABLE IF NOT EXISTS final_evidence_sources (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type         VARCHAR(50) NOT NULL DEFAULT 'other',
    title               VARCHAR(500),
    authors             TEXT,
    year                INTEGER,
    doi                 VARCHAR(200),
    url                 TEXT,
    description         TEXT,
    source_candidate_id UUID,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_evidence_source_type CHECK (
        source_type IN ('atlas', 'paper', 'manual', 'llm', 'web', 'database', 'other')
    )
);

CREATE TABLE IF NOT EXISTS final_evidence_items (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id           UUID REFERENCES final_evidence_sources(id) ON DELETE SET NULL,
    evidence_text       TEXT,
    page                VARCHAR(50),
    table_name          VARCHAR(200),
    figure_name         VARCHAR(200),
    extraction_method   VARCHAR(50) DEFAULT 'parser',
    confidence          FLOAT,
    source_candidate_id UUID,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_evidence_extraction CHECK (
        extraction_method IN ('manual', 'llm', 'rule', 'parser', 'other')
    )
);

CREATE TABLE IF NOT EXISTS final_coarse_brain_regions (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_code         VARCHAR(100) NOT NULL UNIQUE,
    cn_name             VARCHAR(500) NOT NULL,
    en_name             VARCHAR(500),
    abbr                VARCHAR(200),
    laterality          VARCHAR(20) DEFAULT 'unknown',
    region_category     VARCHAR(50) DEFAULT 'unknown',
    anatomical_level    VARCHAR(50) DEFAULT 'coarse',
    parent_region_id    UUID REFERENCES final_coarse_brain_regions(id) ON DELETE SET NULL,
    description         TEXT,
    clinical_note       TEXT,
    status              VARCHAR(20) DEFAULT 'active',
    source_candidate_id UUID UNIQUE,
    promoted_at         TIMESTAMPTZ,
    promoted_by         VARCHAR(100),
    extra_metadata      JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_coarse_laterality CHECK (
        laterality IN ('left', 'right', 'bilateral', 'midline', 'unknown')
    ),
    CONSTRAINT chk_final_coarse_status CHECK (
        status IN ('active', 'deprecated')
    ),
    CONSTRAINT chk_final_coarse_parent_not_self CHECK (
        parent_region_id IS NULL OR parent_region_id <> id
    )
);

CREATE TABLE IF NOT EXISTS final_coarse_brain_region_aliases (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id           UUID NOT NULL REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    alias               VARCHAR(500) NOT NULL,
    alias_type          VARCHAR(50) DEFAULT 'other',
    language            VARCHAR(20) DEFAULT 'unknown',
    source              VARCHAR(200),
    source_candidate_id UUID,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_alias_type CHECK (
        alias_type IN ('cn', 'en', 'abbr', 'synonym', 'atlas_name', 'other')
    )
);

CREATE TABLE IF NOT EXISTS final_coarse_brain_region_relations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_region_id    UUID NOT NULL REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    relation_type       VARCHAR(50) NOT NULL,
    target_region_id    UUID NOT NULL REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    confidence          FLOAT,
    evidence_id         UUID REFERENCES final_evidence_items(id) ON DELETE SET NULL,
    source_candidate_id UUID UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_cbr_relation_type CHECK (
        relation_type IN ('part_of', 'has_part', 'belongs_to_system', 'adjacent_to', 'related_to')
    ),
    CONSTRAINT chk_final_cbr_not_self CHECK (source_region_id <> target_region_id),
    UNIQUE (source_region_id, relation_type, target_region_id)
);

CREATE TABLE IF NOT EXISTS final_atlas_resources (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    atlas_code          VARCHAR(100) NOT NULL UNIQUE,
    atlas_name          VARCHAR(255) NOT NULL,
    version             VARCHAR(100),
    resource_type       VARCHAR(50) DEFAULT 'atlas',
    species             VARCHAR(100) DEFAULT 'human',
    space               VARCHAR(100),
    description         TEXT,
    source_url          TEXT,
    file_manifest       JSONB DEFAULT '{}',
    source_candidate_id UUID UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_atlas_resource_type CHECK (
        resource_type IN ('atlas', 'spatial_atlas', 'connectivity_atlas', 'molecular_atlas', 'other')
    )
);

CREATE TABLE IF NOT EXISTS final_atlas_labels (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    atlas_id            UUID NOT NULL REFERENCES final_atlas_resources(id) ON DELETE CASCADE,
    label_value         INTEGER NOT NULL,
    raw_name            VARCHAR(500) NOT NULL,
    parsed_name         VARCHAR(500),
    cn_name_candidate   VARCHAR(500),
    abbr                VARCHAR(200),
    laterality          VARCHAR(20) DEFAULT 'unknown',
    parent_name_candidate VARCHAR(500),
    voxel_count         INTEGER,
    volume_mm3          FLOAT,
    centroid_mni        JSONB,
    bbox                JSONB,
    extra_metadata      JSONB DEFAULT '{}',
    source_candidate_id UUID UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_atlas_label_laterality CHECK (
        laterality IN ('left', 'right', 'bilateral', 'midline', 'unknown')
    ),
    UNIQUE (atlas_id, label_value)
);

CREATE TABLE IF NOT EXISTS final_coarse_region_atlas_mappings (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    coarse_region_id    UUID REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    atlas_label_id      UUID NOT NULL REFERENCES final_atlas_labels(id) ON DELETE CASCADE,
    mapping_type        VARCHAR(50) NOT NULL,
    mapping_direction   VARCHAR(30) DEFAULT 'atlas_to_coarse',
    confidence          FLOAT,
    mapping_method      VARCHAR(30) DEFAULT 'rule',
    evidence_text       TEXT,
    evidence_id         UUID REFERENCES final_evidence_items(id) ON DELETE SET NULL,
    source_candidate_id UUID UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_mapping_type CHECK (
        mapping_type IN (
            'exact_match', 'part_of', 'has_part', 'merge_to_one', 'split_from_one', 'unmapped'
        )
    ),
    CONSTRAINT chk_final_mapping_direction CHECK (
        mapping_direction IN ('atlas_to_coarse', 'coarse_to_atlas', 'bidirectional')
    ),
    CONSTRAINT chk_final_mapping_method CHECK (
        mapping_method IN ('rule', 'llm', 'manual', 'imported')
    ),
    UNIQUE (atlas_label_id, mapping_type, coarse_region_id)
);

CREATE TABLE IF NOT EXISTS final_coarse_region_connections (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_region_id    UUID NOT NULL REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    target_region_id    UUID NOT NULL REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    connection_type     VARCHAR(50) DEFAULT 'unknown',
    directionality      VARCHAR(20) DEFAULT 'unknown',
    strength            FLOAT,
    confidence          FLOAT,
    evidence_id         UUID REFERENCES final_evidence_items(id) ON DELETE SET NULL,
    source_candidate_id UUID UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_conn_type CHECK (
        connection_type IN ('structural', 'functional', 'effective', 'anatomical', 'unknown')
    ),
    CONSTRAINT chk_final_conn_dir CHECK (
        directionality IN ('directed', 'undirected', 'unknown')
    ),
    CONSTRAINT chk_final_conn_not_self CHECK (source_region_id <> target_region_id)
);

CREATE TABLE IF NOT EXISTS final_coarse_circuits (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    circuit_code        VARCHAR(100) NOT NULL UNIQUE,
    cn_name             VARCHAR(500) NOT NULL,
    en_name             VARCHAR(500),
    description         TEXT,
    function_summary    TEXT,
    source_candidate_id UUID UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS final_coarse_circuit_steps (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    circuit_id          UUID NOT NULL REFERENCES final_coarse_circuits(id) ON DELETE CASCADE,
    step_order          INTEGER NOT NULL,
    source_region_id    UUID NOT NULL REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    target_region_id    UUID NOT NULL REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    connection_id       UUID REFERENCES final_coarse_region_connections(id) ON DELETE SET NULL,
    relation_type       VARCHAR(50) DEFAULT 'connects_to',
    evidence_id         UUID REFERENCES final_evidence_items(id) ON DELETE SET NULL,
    source_candidate_id UUID UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_final_step_relation CHECK (
        relation_type IN ('projects_to', 'connects_to', 'modulates', 'unknown')
    ),
    UNIQUE (circuit_id, step_order)
);

CREATE TABLE IF NOT EXISTS final_coarse_region_function_annotations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id           UUID NOT NULL REFERENCES final_coarse_brain_regions(id) ON DELETE CASCADE,
    function_name       VARCHAR(500) NOT NULL,
    function_category   VARCHAR(200),
    description         TEXT,
    evidence_id         UUID REFERENCES final_evidence_items(id) ON DELETE SET NULL,
    confidence          FLOAT,
    source_candidate_id UUID UNIQUE,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_final_coarse_regions_cn ON final_coarse_brain_regions(cn_name);
CREATE INDEX IF NOT EXISTS idx_final_coarse_regions_en ON final_coarse_brain_regions(en_name);
CREATE INDEX IF NOT EXISTS idx_final_aliases_region ON final_coarse_brain_region_aliases(region_id);
CREATE INDEX IF NOT EXISTS idx_final_aliases_alias_lower ON final_coarse_brain_region_aliases((lower(alias)));
CREATE INDEX IF NOT EXISTS idx_final_atlas_labels_atlas ON final_atlas_labels(atlas_id);
CREATE INDEX IF NOT EXISTS idx_final_atlas_labels_raw_name ON final_atlas_labels(raw_name);
CREATE INDEX IF NOT EXISTS idx_final_mappings_region ON final_coarse_region_atlas_mappings(coarse_region_id);
CREATE INDEX IF NOT EXISTS idx_final_mappings_label ON final_coarse_region_atlas_mappings(atlas_label_id);
CREATE INDEX IF NOT EXISTS idx_final_mappings_type ON final_coarse_region_atlas_mappings(mapping_type);
CREATE INDEX IF NOT EXISTS idx_final_conn_pair ON final_coarse_region_connections(source_region_id, target_region_id);
CREATE INDEX IF NOT EXISTS idx_final_circuit_steps_order ON final_coarse_circuit_steps(circuit_id, step_order);
