-- 009_create_indexes.sql
set search_path to neurokg, public;

-- organism
create index if not exists idx_organism_species on organism(species);
create index if not exists idx_organism_status on organism(status);

-- anatomical_system
create index if not exists idx_anatomical_system_organism_id on anatomical_system(organism_id);
create index if not exists idx_anatomical_system_status on anatomical_system(status);

-- organ
create index if not exists idx_organ_system_id on organ(system_id);
create index if not exists idx_organ_status on organ(status);

-- brain_division
create index if not exists idx_brain_division_organ_id on brain_division(organ_id);
create index if not exists idx_brain_division_division_type on brain_division(division_type);
create index if not exists idx_brain_division_status on brain_division(status);

-- major_brain_region
create index if not exists idx_major_region_organism_id on major_brain_region(organism_id);
create index if not exists idx_major_region_division_id on major_brain_region(division_id);
create index if not exists idx_major_region_laterality on major_brain_region(laterality);
create index if not exists idx_major_region_category on major_brain_region(region_category);
create index if not exists idx_major_region_ontology_source on major_brain_region(ontology_source);
create index if not exists idx_major_region_status on major_brain_region(status);

-- sub_brain_region
create index if not exists idx_sub_region_organism_id on sub_brain_region(organism_id);
create index if not exists idx_sub_region_division_id on sub_brain_region(division_id);
create index if not exists idx_sub_region_parent_major_region_id on sub_brain_region(parent_major_region_id);
create index if not exists idx_sub_region_laterality on sub_brain_region(laterality);
create index if not exists idx_sub_region_category on sub_brain_region(region_category);
create index if not exists idx_sub_region_ontology_source on sub_brain_region(ontology_source);
create index if not exists idx_sub_region_status on sub_brain_region(status);

-- allen_brain_region
create index if not exists idx_allen_region_organism_id on allen_brain_region(organism_id);
create index if not exists idx_allen_region_division_id on allen_brain_region(division_id);
create index if not exists idx_allen_region_parent_sub_region_id on allen_brain_region(parent_sub_region_id);
create index if not exists idx_allen_region_laterality on allen_brain_region(laterality);
create index if not exists idx_allen_region_category on allen_brain_region(region_category);
create index if not exists idx_allen_region_ontology_source on allen_brain_region(ontology_source);
create index if not exists idx_allen_region_status on allen_brain_region(status);

-- major_connection
create index if not exists idx_major_connection_source_id on major_connection(source_major_region_id);
create index if not exists idx_major_connection_target_id on major_connection(target_major_region_id);
create index if not exists idx_major_connection_modality on major_connection(connection_modality);
create index if not exists idx_major_connection_relation_type on major_connection(relation_type);
create index if not exists idx_major_connection_validation_status on major_connection(validation_status);
create index if not exists idx_major_connection_status on major_connection(status);
create index if not exists idx_major_connection_source_target on major_connection(source_major_region_id, target_major_region_id);

-- sub_connection
create index if not exists idx_sub_connection_source_id on sub_connection(source_sub_region_id);
create index if not exists idx_sub_connection_target_id on sub_connection(target_sub_region_id);
create index if not exists idx_sub_connection_modality on sub_connection(connection_modality);
create index if not exists idx_sub_connection_validation_status on sub_connection(validation_status);
create index if not exists idx_sub_connection_status on sub_connection(status);
create index if not exists idx_sub_connection_source_target on sub_connection(source_sub_region_id, target_sub_region_id);

-- allen_connection
create index if not exists idx_allen_connection_source_id on allen_connection(source_allen_region_id);
create index if not exists idx_allen_connection_target_id on allen_connection(target_allen_region_id);
create index if not exists idx_allen_connection_modality on allen_connection(connection_modality);
create index if not exists idx_allen_connection_validation_status on allen_connection(validation_status);
create index if not exists idx_allen_connection_status on allen_connection(status);
create index if not exists idx_allen_connection_source_target on allen_connection(source_allen_region_id, target_allen_region_id);

-- major_circuit
create index if not exists idx_major_circuit_kind on major_circuit(circuit_kind);
create index if not exists idx_major_circuit_loop_type on major_circuit(loop_type);
create index if not exists idx_major_circuit_cycle_verified on major_circuit(cycle_verified);
create index if not exists idx_major_circuit_validation_status on major_circuit(validation_status_circuit);
create index if not exists idx_major_circuit_status on major_circuit(status);

-- sub_circuit
create index if not exists idx_sub_circuit_kind on sub_circuit(circuit_kind);
create index if not exists idx_sub_circuit_loop_type on sub_circuit(loop_type);
create index if not exists idx_sub_circuit_cycle_verified on sub_circuit(cycle_verified);
create index if not exists idx_sub_circuit_validation_status on sub_circuit(validation_status_circuit);
create index if not exists idx_sub_circuit_status on sub_circuit(status);

-- allen_circuit
create index if not exists idx_allen_circuit_kind on allen_circuit(circuit_kind);
create index if not exists idx_allen_circuit_loop_type on allen_circuit(loop_type);
create index if not exists idx_allen_circuit_cycle_verified on allen_circuit(cycle_verified);
create index if not exists idx_allen_circuit_validation_status on allen_circuit(validation_status_circuit);
create index if not exists idx_allen_circuit_status on allen_circuit(status);

-- evidence
create index if not exists idx_evidence_pmid on evidence(pmid);
create index if not exists idx_evidence_doi on evidence(doi);
create index if not exists idx_evidence_publication_year on evidence(publication_year);
create index if not exists idx_evidence_type on evidence(evidence_type);
create index if not exists idx_evidence_status on evidence(status);

-- circuit nodes
create index if not exists idx_major_circuit_node_major_region_id on major_circuit_node(major_region_id);
create index if not exists idx_major_circuit_node_order on major_circuit_node(major_circuit_id, node_order);
create index if not exists idx_sub_circuit_node_sub_region_id on sub_circuit_node(sub_region_id);
create index if not exists idx_sub_circuit_node_order on sub_circuit_node(sub_circuit_id, node_order);
create index if not exists idx_allen_circuit_node_allen_region_id on allen_circuit_node(allen_region_id);
create index if not exists idx_allen_circuit_node_order on allen_circuit_node(allen_circuit_id, node_order);

-- circuit connections
create index if not exists idx_major_circuit_connection_major_connection_id on major_circuit_connection(major_connection_id);
create index if not exists idx_major_circuit_connection_order on major_circuit_connection(major_circuit_id, edge_order);
create index if not exists idx_sub_circuit_connection_sub_connection_id on sub_circuit_connection(sub_connection_id);
create index if not exists idx_sub_circuit_connection_order on sub_circuit_connection(sub_circuit_id, edge_order);
create index if not exists idx_allen_circuit_connection_allen_connection_id on allen_circuit_connection(allen_connection_id);
create index if not exists idx_allen_circuit_connection_order on allen_circuit_connection(allen_circuit_id, edge_order);

-- connection evidence
create index if not exists idx_major_connection_evidence_evidence_id on major_connection_evidence(evidence_id);
create index if not exists idx_sub_connection_evidence_evidence_id on sub_connection_evidence(evidence_id);
create index if not exists idx_allen_connection_evidence_evidence_id on allen_connection_evidence(evidence_id);

-- circuit evidence
create index if not exists idx_major_circuit_evidence_evidence_id on major_circuit_evidence(evidence_id);
create index if not exists idx_sub_circuit_evidence_evidence_id on sub_circuit_evidence(evidence_id);
create index if not exists idx_allen_circuit_evidence_evidence_id on allen_circuit_evidence(evidence_id);

-- extensions
create index if not exists idx_allen_brain_region_ext_allen_atlas_id on allen_brain_region_ext(allen_atlas_id);
create index if not exists idx_allen_brain_region_ext_allen_acronym on allen_brain_region_ext(allen_acronym);

create index if not exists idx_major_conn_structural_measurement_method on major_connection_structural_ext(measurement_method);
create index if not exists idx_sub_conn_structural_measurement_method on sub_connection_structural_ext(measurement_method);
create index if not exists idx_allen_conn_structural_measurement_method on allen_connection_structural_ext(measurement_method);

create index if not exists idx_major_conn_functional_condition_label on major_connection_functional_ext(condition_label);
create index if not exists idx_major_conn_functional_p_value on major_connection_functional_ext(p_value);
create index if not exists idx_sub_conn_functional_condition_label on sub_connection_functional_ext(condition_label);
create index if not exists idx_sub_conn_functional_p_value on sub_connection_functional_ext(p_value);
create index if not exists idx_allen_conn_functional_condition_label on allen_connection_functional_ext(condition_label);
create index if not exists idx_allen_conn_functional_p_value on allen_connection_functional_ext(p_value);

create index if not exists idx_major_circuit_functional_condition_label on major_circuit_functional_ext(condition_label);
create index if not exists idx_sub_circuit_functional_condition_label on sub_circuit_functional_ext(condition_label);
create index if not exists idx_allen_circuit_functional_condition_label on allen_circuit_functional_ext(condition_label);
