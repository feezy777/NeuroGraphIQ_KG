create schema if not exists workbench;

-- 1) Expand uploaded_file so it can fully replace file_record.
alter table if exists workbench.uploaded_file
  add column if not exists version integer not null default 1;
alter table if exists workbench.uploaded_file
  add column if not exists checksum text not null default '';
alter table if exists workbench.uploaded_file
  add column if not exists path text not null default '';
alter table if exists workbench.uploaded_file
  add column if not exists latest_validate_task_id text not null default '';
alter table if exists workbench.uploaded_file
  add column if not exists latest_map_task_id text not null default '';
alter table if exists workbench.uploaded_file
  add column if not exists latest_ingest_task_id text not null default '';

-- 2) Backfill uploaded_file from file_record (newer updated_at wins).
do $$
begin
  if exists (
    select 1
    from information_schema.tables
    where table_schema = 'workbench' and table_name = 'file_record'
  ) then
    execute $sql$
      insert into workbench.uploaded_file (
        id,
        file_name,
        file_type,
        mime_type,
        storage_path,
        content_ref,
        size_bytes,
        upload_status,
        source,
        metadata_json,
        tags_json,
        latest_parse_task_id,
        latest_extract_task_id,
        latest_commit_task_id,
        latest_validate_task_id,
        latest_map_task_id,
        latest_ingest_task_id,
        version,
        checksum,
        path,
        created_at,
        updated_at,
        deleted_at
      )
      select
        fr.file_id,
        fr.filename,
        fr.file_type,
        coalesce(to_jsonb(fr)->>'mime_type', ''),
        coalesce(to_jsonb(fr)->>'path', ''),
        coalesce(to_jsonb(fr)->>'path', ''),
        coalesce((to_jsonb(fr)->>'size_bytes')::bigint, 0),
        coalesce(to_jsonb(fr)->>'status', 'uploaded'),
        coalesce(to_jsonb(fr)->>'source', 'upload'),
        coalesce((to_jsonb(fr)->'metadata_json'), '{}'::jsonb),
        coalesce((to_jsonb(fr)->'tags_json'), '[]'::jsonb),
        coalesce(to_jsonb(fr)->>'latest_parse_task_id', ''),
        coalesce(to_jsonb(fr)->>'latest_extract_task_id', ''),
        coalesce(to_jsonb(fr)->>'latest_commit_task_id', ''),
        coalesce(to_jsonb(fr)->>'latest_validate_task_id', ''),
        coalesce(to_jsonb(fr)->>'latest_map_task_id', ''),
        coalesce(to_jsonb(fr)->>'latest_ingest_task_id', ''),
        coalesce((to_jsonb(fr)->>'version')::integer, 1),
        coalesce(to_jsonb(fr)->>'checksum', ''),
        coalesce(to_jsonb(fr)->>'path', ''),
        fr.created_at,
        fr.updated_at,
        null
      from workbench.file_record fr
      on conflict (id) do update
      set
        file_name = excluded.file_name,
        file_type = excluded.file_type,
        mime_type = excluded.mime_type,
        storage_path = excluded.storage_path,
        content_ref = excluded.content_ref,
        size_bytes = excluded.size_bytes,
        upload_status = excluded.upload_status,
        source = excluded.source,
        metadata_json = excluded.metadata_json,
        tags_json = excluded.tags_json,
        latest_parse_task_id = excluded.latest_parse_task_id,
        latest_extract_task_id = excluded.latest_extract_task_id,
        latest_commit_task_id = excluded.latest_commit_task_id,
        latest_validate_task_id = excluded.latest_validate_task_id,
        latest_map_task_id = excluded.latest_map_task_id,
        latest_ingest_task_id = excluded.latest_ingest_task_id,
        version = excluded.version,
        checksum = excluded.checksum,
        path = excluded.path,
        updated_at = excluded.updated_at,
        deleted_at = null
      where workbench.uploaded_file.updated_at <= excluded.updated_at
    $sql$;
  end if;
end $$;

-- 3) Drop all FK constraints that still point to workbench.file_record.
do $$
declare
  r record;
begin
  if exists (
    select 1
    from information_schema.tables
    where table_schema = 'workbench' and table_name = 'file_record'
  ) then
    for r in
      select c.conname, c.conrelid::regclass::text as child_table
      from pg_constraint c
      where c.contype = 'f'
        and c.confrelid = 'workbench.file_record'::regclass
    loop
      execute format('alter table %s drop constraint if exists %I', r.child_table, r.conname);
    end loop;
  end if;
end $$;

-- 4) Recreate FKs to workbench.uploaded_file(id).
do $$
begin
  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='parsed_document')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='parsed_document' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='parsed_document_file_id_fkey' and conrelid='workbench.parsed_document'::regclass) then
    alter table workbench.parsed_document
      add constraint parsed_document_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='content_chunk')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='content_chunk' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='content_chunk_file_id_fkey' and conrelid='workbench.content_chunk'::regclass) then
    alter table workbench.content_chunk
      add constraint content_chunk_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='file_blob')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='file_blob' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='file_blob_file_id_fkey' and conrelid='workbench.file_blob'::regclass) then
    alter table workbench.file_blob
      add constraint file_blob_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='file_revision')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='file_revision' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='file_revision_file_id_fkey' and conrelid='workbench.file_revision'::regclass) then
    alter table workbench.file_revision
      add constraint file_revision_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='candidate_entity')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='candidate_entity' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='candidate_entity_file_id_fkey' and conrelid='workbench.candidate_entity'::regclass) then
    alter table workbench.candidate_entity
      add constraint candidate_entity_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='candidate_relation')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='candidate_relation' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='candidate_relation_file_id_fkey' and conrelid='workbench.candidate_relation'::regclass) then
    alter table workbench.candidate_relation
      add constraint candidate_relation_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='candidate_connection')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='candidate_connection' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='candidate_connection_file_id_fkey' and conrelid='workbench.candidate_connection'::regclass) then
    alter table workbench.candidate_connection
      add constraint candidate_connection_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='candidate_circuit')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='candidate_circuit' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='candidate_circuit_file_id_fkey' and conrelid='workbench.candidate_circuit'::regclass) then
    alter table workbench.candidate_circuit
      add constraint candidate_circuit_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='validation_run')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='validation_run' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='validation_run_file_id_fkey' and conrelid='workbench.validation_run'::regclass) then
    alter table workbench.validation_run
      add constraint validation_run_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='granularity_mapping')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='granularity_mapping' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='granularity_mapping_file_id_fkey' and conrelid='workbench.granularity_mapping'::regclass) then
    alter table workbench.granularity_mapping
      add constraint granularity_mapping_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;

  if exists (select 1 from information_schema.tables where table_schema='workbench' and table_name='ingestion_run')
     and exists (select 1 from information_schema.columns where table_schema='workbench' and table_name='ingestion_run' and column_name='file_id')
     and not exists (select 1 from pg_constraint where conname='ingestion_run_file_id_fkey' and conrelid='workbench.ingestion_run'::regclass) then
    alter table workbench.ingestion_run
      add constraint ingestion_run_file_id_fkey
      foreign key (file_id) references workbench.uploaded_file(id) on delete cascade;
  end if;
end $$;

-- 5) Remove deprecated table after FK migration.
drop table if exists workbench.file_record;

-- 6) Indexes for uploaded_file main-path reads.
create index if not exists idx_uploaded_file_status_created on workbench.uploaded_file(upload_status, created_at desc);
create index if not exists idx_uploaded_file_updated on workbench.uploaded_file(updated_at desc);
