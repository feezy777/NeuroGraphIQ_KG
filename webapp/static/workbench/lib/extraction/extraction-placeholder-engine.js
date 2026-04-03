const REGION_SEEDS = [
  "Hippocampus",
  "Amygdala",
  "Thalamus",
  "Striatum",
  "Cingulate Cortex",
  "Insula Cortex",
  "Temporal Lobe",
  "Parietal Lobe",
  "Frontal Lobe",
  "Cerebellum",
];

function makeId(prefix, seed, index) {
  const slug = String(seed || "item")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
  return `${prefix}_${slug}_${index + 1}`;
}

export function runPlaceholderExtraction({
  ontology,
  files,
  targets,
  mode,
  runtimeMode = "placeholder",
  output,
  granularity = "coarse",
  tableMapping = {},
  deepseek = null,
}) {
  const selectedTargets = Array.isArray(targets) && targets.length ? targets : ["region", "circuit", "connection"];
  const fileNames = (files || []).map((file) => file.filename || file.file_id);

  const entities = [];
  const relations = [];
  const circuits = [];

  const regionCount = Math.max(6, Math.min(18, (files?.length || 1) * 5));
  for (let i = 0; i < regionCount; i += 1) {
    const name = REGION_SEEDS[i % REGION_SEEDS.length];
    entities.push({
      id: makeId("cand_region", name, i),
      type: "brain_region",
      name,
      granularity,
      source: fileNames[i % Math.max(1, fileNames.length)] || "manual",
      confidence: Number((0.65 + (i % 4) * 0.08).toFixed(2)),
      status: "pending",
    });
  }

  if (selectedTargets.includes("connection")) {
    for (let i = 0; i < Math.max(5, regionCount - 2); i += 1) {
      const source = entities[i % entities.length];
      const target = entities[(i + 2) % entities.length];
      relations.push({
        id: makeId("cand_relation", `${source.name}_${target.name}`, i),
        source: source.id,
        target: target.id,
        relationType: i % 2 === 0 ? "direct_structural_connection" : "same_circuit_member",
        confidence: Number((0.61 + (i % 5) * 0.07).toFixed(2)),
        status: "pending",
      });
    }
  }

  if (selectedTargets.includes("circuit")) {
    for (let i = 0; i < 3; i += 1) {
      const nodeIds = [entities[i].id, entities[i + 1].id, entities[i + 2].id];
      circuits.push({
        id: makeId("cand_circuit", `major_loop_${i + 1}`, i),
        name: `major_loop_${i + 1}`,
        family: i === 0 ? "corticostriatal_thalamocortical" : i === 1 ? "hippocampal_memory" : "salience_insula_cingulate",
        nodeIds,
        confidence: Number((0.67 + i * 0.1).toFixed(2)),
        status: "pending",
      });
    }
  }

  return {
    jobMeta: {
      mode,
      runtimeMode,
      output,
      targets: selectedTargets,
      ontologyId: ontology?.file_id || "",
      sourceFiles: fileNames,
      granularity,
      tableMapping,
      deepseek: deepseek || null,
    },
    summary: {
      entities: entities.length,
      relations: relations.length,
      circuits: circuits.length,
    },
    candidates: {
      entities,
      relations,
      circuits,
    },
  };
}
