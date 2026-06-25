-- NeuroGraphIQ KG V3 Database Schema
-- PostgreSQL Database: NeuroGraphIQ_KG_V3
-- ============================================================

-- Enable UUID extension
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================
-- ENUM TYPES
-- ============================================================

CREATE TYPE import_status AS ENUM (
    'pending', 'running', 'parsed', 'validating', 'validated',
    'llm_reviewing', 'llm_reviewed', 'reviewing', 'completed', 'failed'
);

CREATE TYPE resource_type AS ENUM (
    'aal3', 'brainnetome', 'allen', 'freesurfer',
    'hcp_mmp', 'julich_brain', 'braininfo', 'interlex', 'other'
);

CREATE TYPE granularity_level AS ENUM (
    'macro', 'meso', 'micro', 'molecular', 'term'
);

CREATE TYPE data_type AS ENUM (
    'atlas', 'connectivity', 'gene_expression', 'ontology', 'parcellation', 'mixed'
);

CREATE TYPE severity_level AS ENUM ('info', 'warning', 'error', 'critical');

CREATE TYPE review_status AS ENUM ('pending', 'approved', 'modified', 'rejected');

CREATE TYPE llm_provider AS ENUM ('deepseek', 'kimi');

CREATE TYPE item_type AS ENUM (
    'region', 'connection', 'function', 'molecular', 'term', 'mapping'
);


-- ============================================================
-- LAYER 1: REGISTRATION (注册层)
-- ============================================================

CREATE TABLE resource_registry (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    resource_name   VARCHAR(255) NOT NULL,
    resource_type   resource_type NOT NULL,
    version         VARCHAR(100),
    source_url      TEXT,
    source_paper    TEXT,
    granularity     granularity_level,
    data_type       data_type,
    local_path      TEXT,
    import_time     TIMESTAMPTZ DEFAULT NOW(),
    import_status   import_status DEFAULT 'pending',
    description     TEXT,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (resource_name, version)
);

CREATE TABLE file_registry (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    resource_id     UUID REFERENCES resource_registry(id) ON DELETE CASCADE,
    file_name       VARCHAR(500) NOT NULL,
    file_path       TEXT NOT NULL,
    file_type       VARCHAR(50),
    sha256          CHAR(64) NOT NULL,
    file_size_bytes BIGINT,
    source_code     VARCHAR(100),
    source_version  VARCHAR(100),
    uploaded_at     TIMESTAMPTZ DEFAULT NOW(),
    intermediate_json       JSONB,
    intermediate_status     VARCHAR(20) DEFAULT 'pending',
    intermediate_error      TEXT,
    intermediate_parsed_at  TIMESTAMPTZ,
    UNIQUE (sha256)
);


-- ============================================================
-- LAYER 2: TASK (任务层)
-- ============================================================

CREATE TABLE import_tasks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    resource_id     UUID REFERENCES resource_registry(id) ON DELETE CASCADE,
    resource_type   resource_type NOT NULL,
    parser_name     VARCHAR(100) NOT NULL,
    input_file_id   UUID REFERENCES file_registry(id),
    input_file_path TEXT,
    source_key      VARCHAR(100),
    status          import_status DEFAULT 'pending',
    error_message   TEXT,
    started_at      TIMESTAMPTZ,
    finished_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE llm_configs (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider        llm_provider NOT NULL,
    api_key         TEXT NOT NULL,
    model           VARCHAR(100) NOT NULL,
    base_url        TEXT,
    temperature     FLOAT DEFAULT 0.3,
    max_tokens      INTEGER DEFAULT 2048,
    is_global       BOOLEAN DEFAULT FALSE,
    task_id         UUID REFERENCES import_tasks(id) ON DELETE CASCADE,
    config_name     VARCHAR(200),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT chk_global_or_task CHECK (
        (is_global = TRUE AND task_id IS NULL) OR
        (is_global = FALSE AND task_id IS NOT NULL)
    )
);


-- ============================================================
-- LAYER 3: STAGING (中间结果层)
-- ============================================================

CREATE TABLE staging_regions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    original_name   VARCHAR(500) NOT NULL,
    abbr            VARCHAR(100),
    full_name       VARCHAR(500),
    hemisphere      VARCHAR(10),             -- L, R, bilateral
    parent_region   VARCHAR(500),
    coordinates_mni JSONB,                   -- {"x": 0, "y": 0, "z": 0}
    bounding_box    JSONB,
    granularity     granularity_level,
    source_id       VARCHAR(200),            -- original ID in source atlas
    ontology_id     VARCHAR(200),
    label_index     INTEGER,
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE staging_connections (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    region_from     VARCHAR(500) NOT NULL,
    region_to       VARCHAR(500) NOT NULL,
    connection_type VARCHAR(100),            -- structural, functional, effective
    strength        FLOAT,
    directionality  VARCHAR(20),             -- unidirectional, bidirectional
    evidence        TEXT,
    dataset_ref     VARCHAR(200),
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE staging_functions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    region_ref      VARCHAR(500),
    function_desc   TEXT NOT NULL,
    function_domain VARCHAR(200),            -- cognitive, sensory, motor, etc.
    evidence        TEXT,
    source_ref      VARCHAR(200),
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE staging_molecular_attributes (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    gene_symbol     VARCHAR(100),
    gene_id         VARCHAR(100),
    expression_level FLOAT,
    expression_unit VARCHAR(50),
    region_ref      VARCHAR(500),
    structure_id    VARCHAR(200),
    dataset_ref     VARCHAR(200),
    specimen_id     VARCHAR(200),
    age_group       VARCHAR(50),
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE staging_terms (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    term            VARCHAR(500) NOT NULL,
    definition      TEXT,
    synonyms        JSONB DEFAULT '[]',      -- array of strings
    ontology_id     VARCHAR(200),
    ontology_source VARCHAR(100),            -- interlex, braininfo, etc.
    parent_term     VARCHAR(500),
    source_url      TEXT,
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE staging_mappings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    source_name     VARCHAR(500) NOT NULL,
    source_atlas    VARCHAR(100),
    target_name     VARCHAR(500),
    target_atlas    VARCHAR(100),
    mapping_type    VARCHAR(100),            -- exact, broad, narrow, related
    confidence      FLOAT CHECK (confidence >= 0 AND confidence <= 1),
    evidence        TEXT,
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
-- LAYER 4: QUALITY & LLM VALIDATION
-- ============================================================

CREATE TABLE quality_reports (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    check_type      VARCHAR(100) NOT NULL,   -- empty_name, duplicate_id, missing_version, etc.
    severity        severity_level NOT NULL,
    message         TEXT NOT NULL,
    affected_id     UUID,
    affected_table  VARCHAR(100),
    affected_field  VARCHAR(100),
    auto_fixable    BOOLEAN DEFAULT FALSE,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE llm_validation_results (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id             UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    item_id             UUID NOT NULL,
    item_type           item_type NOT NULL,
    cn_name_candidates  JSONB DEFAULT '[]',   -- [{"name": "...", "confidence": 0.9}]
    parent_candidates   JSONB DEFAULT '[]',
    mapping_candidates  JSONB DEFAULT '[]',
    anomaly_note        TEXT,
    raw_response        TEXT,
    model_used          VARCHAR(100),
    provider_used       llm_provider,
    prompt_tokens       INTEGER,
    completion_tokens   INTEGER,
    prompt_config       JSONB DEFAULT '{}',
    created_at          TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
-- LAYER 5: REVIEW & PROMOTION (审核与晋级层)
-- ============================================================

CREATE TABLE review_queue (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id             UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    item_id             UUID NOT NULL,
    item_type           item_type NOT NULL,
    original_name       VARCHAR(500),
    cn_name_suggestion  VARCHAR(500),
    mapping_suggestion  VARCHAR(500),
    evidence            TEXT,
    confidence          FLOAT,
    status              review_status DEFAULT 'pending',
    reviewer_note       TEXT,
    reviewed_by         VARCHAR(100),
    reviewed_at         TIMESTAMPTZ,
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE promotion_log (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    item_id         UUID NOT NULL,
    item_type       item_type NOT NULL,
    task_id         UUID REFERENCES import_tasks(id),
    target_table    VARCHAR(100) NOT NULL,
    target_id       UUID,
    promoted_at     TIMESTAMPTZ DEFAULT NOW(),
    promoted_by     VARCHAR(100) DEFAULT 'system'
);


-- ============================================================
-- LAYER 6: OFFICIAL KNOWLEDGE GRAPH (正式库)
-- ============================================================

CREATE TABLE kg_regions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name_en         VARCHAR(500) NOT NULL,
    name_cn         VARCHAR(500),
    abbr            VARCHAR(100),
    hemisphere      VARCHAR(10),
    parent_id       UUID REFERENCES kg_regions(id),
    granularity     granularity_level,
    coordinates_mni JSONB,
    ontology_ids    JSONB DEFAULT '{}',      -- {"aal3": "...", "brainnetome": "..."}
    source_atlases  JSONB DEFAULT '[]',
    description     TEXT,
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE kg_connections (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_from_id  UUID NOT NULL REFERENCES kg_regions(id),
    region_to_id    UUID NOT NULL REFERENCES kg_regions(id),
    connection_type VARCHAR(100),
    strength        FLOAT,
    directionality  VARCHAR(20),
    evidence        TEXT,
    source_atlases  JSONB DEFAULT '[]',
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE kg_functions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    region_id       UUID REFERENCES kg_regions(id),
    function_desc   TEXT NOT NULL,
    function_domain VARCHAR(200),
    evidence        TEXT,
    source_refs     JSONB DEFAULT '[]',
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE kg_molecular (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    gene_symbol     VARCHAR(100),
    gene_id         VARCHAR(100),
    region_id       UUID REFERENCES kg_regions(id),
    expression_level FLOAT,
    expression_unit VARCHAR(50),
    dataset_ref     VARCHAR(200),
    source_refs     JSONB DEFAULT '[]',
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE kg_terms (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    term            VARCHAR(500) NOT NULL UNIQUE,
    definition      TEXT,
    synonyms        JSONB DEFAULT '[]',
    ontology_ids    JSONB DEFAULT '{}',
    parent_id       UUID REFERENCES kg_terms(id),
    source_refs     JSONB DEFAULT '[]',
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE kg_mappings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    source_region_id UUID REFERENCES kg_regions(id),
    target_region_id UUID REFERENCES kg_regions(id),
    source_term_id  UUID REFERENCES kg_terms(id),
    target_term_id  UUID REFERENCES kg_terms(id),
    mapping_type    VARCHAR(100),
    confidence      FLOAT,
    evidence        TEXT,
    extra_attrs     JSONB DEFAULT '{}',
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    updated_at      TIMESTAMPTZ DEFAULT NOW()
);


-- ============================================================
-- INDEXES
-- ============================================================

-- Task-related lookups
CREATE INDEX idx_import_tasks_status ON import_tasks(status);
CREATE INDEX idx_import_tasks_resource_id ON import_tasks(resource_id);
CREATE INDEX idx_import_tasks_resource_type ON import_tasks(resource_type);
CREATE INDEX idx_import_tasks_source_key ON import_tasks(source_key);

CREATE TABLE import_task_versions (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    task_id         UUID NOT NULL REFERENCES import_tasks(id) ON DELETE CASCADE,
    version_number  INTEGER NOT NULL,
    label           VARCHAR(200),
    status_at_save  import_status,
    snapshot        JSONB NOT NULL,
    region_count    INTEGER DEFAULT 0,
    connection_count INTEGER DEFAULT 0,
    term_count      INTEGER DEFAULT 0,
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (task_id, version_number)
);

CREATE INDEX idx_import_task_versions_task_id ON import_task_versions(task_id);

-- Staging table task lookups
CREATE INDEX idx_staging_regions_task_id ON staging_regions(task_id);
CREATE INDEX idx_staging_connections_task_id ON staging_connections(task_id);
CREATE INDEX idx_staging_functions_task_id ON staging_functions(task_id);
CREATE INDEX idx_staging_molecular_task_id ON staging_molecular_attributes(task_id);
CREATE INDEX idx_staging_terms_task_id ON staging_terms(task_id);
CREATE INDEX idx_staging_mappings_task_id ON staging_mappings(task_id);

-- Text search on staging regions
CREATE INDEX idx_staging_regions_name_trgm ON staging_regions USING gin(original_name gin_trgm_ops);

-- Quality and LLM results
CREATE INDEX idx_quality_reports_task_id ON quality_reports(task_id);
CREATE INDEX idx_quality_reports_severity ON quality_reports(severity);
CREATE INDEX idx_llm_validation_task_id ON llm_validation_results(task_id);
CREATE INDEX idx_llm_validation_item ON llm_validation_results(item_id, item_type);

-- Review queue
CREATE INDEX idx_review_queue_task_id ON review_queue(task_id);
CREATE INDEX idx_review_queue_status ON review_queue(status);
CREATE INDEX idx_review_queue_item_type ON review_queue(item_type);

-- Official KG
CREATE INDEX idx_kg_regions_name_en ON kg_regions(name_en);
CREATE INDEX idx_kg_regions_parent ON kg_regions(parent_id);
CREATE INDEX idx_kg_terms_term ON kg_terms(term);
CREATE INDEX idx_kg_connections_from ON kg_connections(region_from_id);
CREATE INDEX idx_kg_connections_to ON kg_connections(region_to_id);
CREATE INDEX idx_kg_molecular_gene ON kg_molecular(gene_symbol);
CREATE INDEX idx_kg_molecular_region ON kg_molecular(region_id);

-- File registry dedup
CREATE INDEX idx_file_registry_sha256 ON file_registry(sha256);
CREATE INDEX idx_file_registry_resource_id ON file_registry(resource_id);

-- LLM configs
CREATE INDEX idx_llm_configs_global ON llm_configs(is_global) WHERE is_global = TRUE;
CREATE INDEX idx_llm_configs_task ON llm_configs(task_id) WHERE task_id IS NOT NULL;


-- ============================================================
-- TRIGGERS: updated_at auto-refresh
-- ============================================================

CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_resource_registry_updated_at
    BEFORE UPDATE ON resource_registry
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_import_tasks_updated_at
    BEFORE UPDATE ON import_tasks
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_llm_configs_updated_at
    BEFORE UPDATE ON llm_configs
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_review_queue_updated_at
    BEFORE UPDATE ON review_queue
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_kg_regions_updated_at
    BEFORE UPDATE ON kg_regions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_kg_connections_updated_at
    BEFORE UPDATE ON kg_connections
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_kg_functions_updated_at
    BEFORE UPDATE ON kg_functions
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_kg_molecular_updated_at
    BEFORE UPDATE ON kg_molecular
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_kg_terms_updated_at
    BEFORE UPDATE ON kg_terms
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

CREATE TRIGGER trg_kg_mappings_updated_at
    BEFORE UPDATE ON kg_mappings
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();
