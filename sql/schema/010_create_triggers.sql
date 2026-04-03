-- 010_create_triggers.sql
set search_path to neurokg, public;

create or replace function set_updated_at()
returns trigger as $$
begin
    new.updated_at = now();
    return new;
end;
$$ language plpgsql;

-- Core tables with updated_at

drop trigger if exists trg_organism_updated_at on organism;
create trigger trg_organism_updated_at
before update on organism
for each row execute function set_updated_at();

drop trigger if exists trg_anatomical_system_updated_at on anatomical_system;
create trigger trg_anatomical_system_updated_at
before update on anatomical_system
for each row execute function set_updated_at();

drop trigger if exists trg_organ_updated_at on organ;
create trigger trg_organ_updated_at
before update on organ
for each row execute function set_updated_at();

drop trigger if exists trg_brain_division_updated_at on brain_division;
create trigger trg_brain_division_updated_at
before update on brain_division
for each row execute function set_updated_at();

drop trigger if exists trg_major_brain_region_updated_at on major_brain_region;
create trigger trg_major_brain_region_updated_at
before update on major_brain_region
for each row execute function set_updated_at();

drop trigger if exists trg_sub_brain_region_updated_at on sub_brain_region;
create trigger trg_sub_brain_region_updated_at
before update on sub_brain_region
for each row execute function set_updated_at();

drop trigger if exists trg_allen_brain_region_updated_at on allen_brain_region;
create trigger trg_allen_brain_region_updated_at
before update on allen_brain_region
for each row execute function set_updated_at();

drop trigger if exists trg_major_connection_updated_at on major_connection;
create trigger trg_major_connection_updated_at
before update on major_connection
for each row execute function set_updated_at();

drop trigger if exists trg_sub_connection_updated_at on sub_connection;
create trigger trg_sub_connection_updated_at
before update on sub_connection
for each row execute function set_updated_at();

drop trigger if exists trg_allen_connection_updated_at on allen_connection;
create trigger trg_allen_connection_updated_at
before update on allen_connection
for each row execute function set_updated_at();

drop trigger if exists trg_major_circuit_updated_at on major_circuit;
create trigger trg_major_circuit_updated_at
before update on major_circuit
for each row execute function set_updated_at();

drop trigger if exists trg_sub_circuit_updated_at on sub_circuit;
create trigger trg_sub_circuit_updated_at
before update on sub_circuit
for each row execute function set_updated_at();

drop trigger if exists trg_allen_circuit_updated_at on allen_circuit;
create trigger trg_allen_circuit_updated_at
before update on allen_circuit
for each row execute function set_updated_at();

drop trigger if exists trg_evidence_updated_at on evidence;
create trigger trg_evidence_updated_at
before update on evidence
for each row execute function set_updated_at();

-- TODO(phase-2):
-- 1) add major/sub/allen hierarchy consistency triggers.
-- 2) add structural/functionality extension consistency triggers.
-- 3) add future RDF/triples export views for split tables.
