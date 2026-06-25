-- Coarse-grain brain region schema (non-destructive; does not drop existing tables).
-- Revision: 20260520_coarse_grain_schema

-- evidence first (referenced by relations)
CREATE TABLE IF NOT EXISTS evidence_sources (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_type     VARCHAR(50) NOT NULL DEFAULT 'other',
    title           VARCHAR(500),
    authors         TEXT,
    year            INTEGER,
    doi             VARCHAR(200),
    url             TEXT,
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_evidence_source_type CHECK (
        source_type IN ('atlas', 'paper', 'manual', 'llm', 'web', 'database', 'other')
    )
);

CREATE TABLE IF NOT EXISTS evidence_items (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_id           UUID REFERENCES evidence_sources(id) ON DELETE SET NULL,
    evidence_text       TEXT,
    page                VARCHAR(50),
    table_name          VARCHAR(200),
    figure_name         VARCHAR(200),
    extraction_method   VARCHAR(50) DEFAULT 'parser',
    confidence          FLOAT,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_evidence_extraction CHECK (
        extraction_method IN ('manual', 'llm', 'rule', 'parser', 'other')
    )
);

CREATE TABLE IF NOT EXISTS coarse_brain_regions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_code     VARCHAR(100) NOT NULL UNIQUE,
    cn_name         VARCHAR(500) NOT NULL,
    en_name         VARCHAR(500),
    abbr            VARCHAR(200),
    laterality      VARCHAR(20) DEFAULT 'unknown',
    region_category VARCHAR(50) DEFAULT 'unknown',
    anatomical_level VARCHAR(50) DEFAULT 'coarse',
    parent_region_id UUID REFERENCES coarse_brain_regions(id) ON DELETE SET NULL,
    description     TEXT,
    clinical_note   TEXT,
    status          VARCHAR(20) DEFAULT 'active',
    extra_metadata  JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_coarse_laterality CHECK (
        laterality IN ('left', 'right', 'bilateral', 'midline', 'unknown')
    ),
    CONSTRAINT chk_coarse_status CHECK (
        status IN ('active', 'candidate', 'deprecated')
    ),
    CONSTRAINT chk_coarse_parent_not_self CHECK (
        parent_region_id IS NULL OR parent_region_id <> id
    )
);

CREATE TABLE IF NOT EXISTS coarse_brain_region_aliases (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id   UUID NOT NULL REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    alias       VARCHAR(500) NOT NULL,
    alias_type  VARCHAR(50) DEFAULT 'other',
    language    VARCHAR(20) DEFAULT 'unknown',
    source      VARCHAR(200),
    created_at  TIMESTAMPTZ DEFAULT NOW(),
    updated_at  TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_alias_type CHECK (
        alias_type IN ('cn', 'en', 'abbr', 'synonym', 'atlas_name', 'other')
    )
);

CREATE TABLE IF NOT EXISTS coarse_brain_region_relations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_region_id    UUID NOT NULL REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    relation_type       VARCHAR(50) NOT NULL,
    target_region_id    UUID NOT NULL REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    confidence          FLOAT,
    evidence_id         UUID REFERENCES evidence_items(id) ON DELETE SET NULL,
    review_status       VARCHAR(20) DEFAULT 'candidate',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_cbr_relation_type CHECK (
        relation_type IN ('part_of', 'has_part', 'belongs_to_system', 'adjacent_to', 'related_to')
    ),
    CONSTRAINT chk_cbr_review CHECK (
        review_status IN ('candidate', 'verified', 'rejected')
    ),
    CONSTRAINT chk_cbr_not_self CHECK (source_region_id <> target_region_id),
    UNIQUE (source_region_id, relation_type, target_region_id)
);

CREATE TABLE IF NOT EXISTS atlas_resources (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    atlas_code      VARCHAR(100) NOT NULL UNIQUE,
    atlas_name      VARCHAR(255) NOT NULL,
    version         VARCHAR(100),
    resource_type   VARCHAR(50) DEFAULT 'atlas',
    species         VARCHAR(100) DEFAULT 'human',
    space           VARCHAR(100),
    description     TEXT,
    source_url      TEXT,
    file_manifest   JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_atlas_resource_type CHECK (
        resource_type IN ('atlas', 'spatial_atlas', 'connectivity_atlas', 'molecular_atlas', 'other')
    )
);

CREATE TABLE IF NOT EXISTS atlas_labels (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    atlas_id            UUID NOT NULL REFERENCES atlas_resources(id) ON DELETE CASCADE,
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
    import_task_id      UUID REFERENCES import_tasks(id) ON DELETE SET NULL,
    extra_metadata      JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_atlas_label_laterality CHECK (
        laterality IN ('left', 'right', 'bilateral', 'midline', 'unknown')
    ),
    UNIQUE (atlas_id, label_value)
);

CREATE TABLE IF NOT EXISTS coarse_region_atlas_mappings (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    coarse_region_id    UUID REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    atlas_label_id      UUID NOT NULL REFERENCES atlas_labels(id) ON DELETE CASCADE,
    mapping_type        VARCHAR(50) NOT NULL,
    mapping_direction   VARCHAR(30) DEFAULT 'atlas_to_coarse',
    confidence          FLOAT,
    mapping_method      VARCHAR(30) DEFAULT 'rule',
    evidence_text       TEXT,
    evidence_id         UUID REFERENCES evidence_items(id) ON DELETE SET NULL,
    review_status       VARCHAR(20) DEFAULT 'candidate',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_mapping_type CHECK (
        mapping_type IN (
            'exact_match', 'part_of', 'has_part', 'merge_to_one', 'split_from_one',
            'candidate', 'unmapped'
        )
    ),
    CONSTRAINT chk_mapping_direction CHECK (
        mapping_direction IN ('atlas_to_coarse', 'coarse_to_atlas', 'bidirectional')
    ),
    CONSTRAINT chk_mapping_method CHECK (
        mapping_method IN ('rule', 'llm', 'manual', 'imported')
    ),
    CONSTRAINT chk_mapping_review CHECK (
        review_status IN ('candidate', 'verified', 'rejected')
    ),
    UNIQUE (atlas_label_id, mapping_type, coarse_region_id)
);

CREATE TABLE IF NOT EXISTS coarse_region_connections (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_region_id    UUID NOT NULL REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    target_region_id    UUID NOT NULL REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    connection_type     VARCHAR(50) DEFAULT 'unknown',
    directionality      VARCHAR(20) DEFAULT 'unknown',
    strength            FLOAT,
    confidence          FLOAT,
    evidence_id         UUID REFERENCES evidence_items(id) ON DELETE SET NULL,
    review_status       VARCHAR(20) DEFAULT 'candidate',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_conn_type CHECK (
        connection_type IN ('structural', 'functional', 'effective', 'anatomical', 'unknown')
    ),
    CONSTRAINT chk_conn_dir CHECK (
        directionality IN ('directed', 'undirected', 'unknown')
    ),
    CONSTRAINT chk_conn_review CHECK (
        review_status IN ('candidate', 'verified', 'rejected')
    ),
    CONSTRAINT chk_conn_not_self CHECK (source_region_id <> target_region_id)
);

CREATE TABLE IF NOT EXISTS coarse_circuits (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    circuit_code    VARCHAR(100) NOT NULL UNIQUE,
    cn_name         VARCHAR(500) NOT NULL,
    en_name         VARCHAR(500),
    description     TEXT,
    function_summary TEXT,
    review_status   VARCHAR(20) DEFAULT 'candidate',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_circuit_review CHECK (
        review_status IN ('candidate', 'verified', 'rejected')
    )
);

CREATE TABLE IF NOT EXISTS coarse_circuit_steps (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    circuit_id          UUID NOT NULL REFERENCES coarse_circuits(id) ON DELETE CASCADE,
    step_order          INTEGER NOT NULL,
    source_region_id    UUID NOT NULL REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    target_region_id    UUID NOT NULL REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    connection_id       UUID REFERENCES coarse_region_connections(id) ON DELETE SET NULL,
    relation_type       VARCHAR(50) DEFAULT 'connects_to',
    evidence_id         UUID REFERENCES evidence_items(id) ON DELETE SET NULL,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_step_relation CHECK (
        relation_type IN ('projects_to', 'connects_to', 'modulates', 'unknown')
    ),
    UNIQUE (circuit_id, step_order)
);

CREATE TABLE IF NOT EXISTS coarse_region_function_annotations (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id           UUID NOT NULL REFERENCES coarse_brain_regions(id) ON DELETE CASCADE,
    function_name       VARCHAR(500) NOT NULL,
    function_category   VARCHAR(200),
    description         TEXT,
    evidence_id         UUID REFERENCES evidence_items(id) ON DELETE SET NULL,
    confidence          FLOAT,
    review_status       VARCHAR(20) DEFAULT 'candidate',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_func_review CHECK (
        review_status IN ('candidate', 'verified', 'rejected')
    )
);

-- indexes
CREATE INDEX IF NOT EXISTS idx_coarse_regions_cn ON coarse_brain_regions(cn_name);
CREATE INDEX IF NOT EXISTS idx_coarse_regions_en ON coarse_brain_regions(en_name);
CREATE INDEX IF NOT EXISTS idx_coarse_aliases_region ON coarse_brain_region_aliases(region_id);
CREATE INDEX IF NOT EXISTS idx_coarse_aliases_alias_lower ON coarse_brain_region_aliases((lower(alias)));
CREATE INDEX IF NOT EXISTS idx_atlas_labels_atlas ON atlas_labels(atlas_id);
CREATE INDEX IF NOT EXISTS idx_atlas_labels_raw_name ON atlas_labels(raw_name);
CREATE INDEX IF NOT EXISTS idx_coarse_mappings_region ON coarse_region_atlas_mappings(coarse_region_id);
CREATE INDEX IF NOT EXISTS idx_coarse_mappings_label ON coarse_region_atlas_mappings(atlas_label_id);
CREATE INDEX IF NOT EXISTS idx_coarse_mappings_type ON coarse_region_atlas_mappings(mapping_type);
CREATE INDEX IF NOT EXISTS idx_coarse_conn_pair ON coarse_region_connections(source_region_id, target_region_id);
CREATE INDEX IF NOT EXISTS idx_circuit_steps_order ON coarse_circuit_steps(circuit_id, step_order);

-- updated_at triggers (reuse function from init_schema if present)
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_proc WHERE proname = 'update_updated_at') THEN
        CREATE OR REPLACE FUNCTION update_updated_at()
        RETURNS TRIGGER AS $fn$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $fn$ LANGUAGE plpgsql;
    END IF;
END $$;

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'evidence_sources', 'evidence_items', 'coarse_brain_regions', 'coarse_brain_region_aliases',
        'coarse_brain_region_relations', 'atlas_resources', 'atlas_labels',
        'coarse_region_atlas_mappings', 'coarse_region_connections', 'coarse_circuits',
        'coarse_circuit_steps', 'coarse_region_function_annotations'
    ]
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS trg_%s_updated_at ON %I; '
            'CREATE TRIGGER trg_%s_updated_at BEFORE UPDATE ON %I '
            'FOR EACH ROW EXECUTE FUNCTION update_updated_at();',
            t, t, t, t
        );
    END LOOP;
END $$;
