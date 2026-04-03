export function buildGraphFromExtraction(result) {
  const entities = result?.candidates?.entities || [];
  const relations = result?.candidates?.relations || [];
  const circuits = result?.candidates?.circuits || [];

  const nodes = [];
  const edges = [];

  for (const entity of entities) {
    nodes.push({
      id: entity.id,
      type: "entity",
      label: entity.name,
      confidence: entity.confidence,
    });
  }

  for (const circuit of circuits) {
    const circuitNodeId = `graph_${circuit.id}`;
    nodes.push({
      id: circuitNodeId,
      type: "circuit",
      label: circuit.name,
      confidence: circuit.confidence,
    });
    for (const nodeId of circuit.nodeIds || []) {
      edges.push({
        id: `edge_circuit_${circuit.id}_${nodeId}`,
        source: circuitNodeId,
        target: nodeId,
        type: "same_circuit_member",
      });
    }
  }

  for (const relation of relations) {
    edges.push({
      id: relation.id,
      source: relation.source,
      target: relation.target,
      type: relation.relationType,
      confidence: relation.confidence,
    });
  }

  return {
    nodes,
    edges,
    review: {
      entities: entities.map((item) => ({
        id: item.id,
        name: item.name,
        type: item.type,
        confidence: item.confidence,
        status: item.status || "pending",
      })),
      relations: relations.map((item) => ({
        id: item.id,
        source: item.source,
        target: item.target,
        relationType: item.relationType,
        confidence: item.confidence,
        status: item.status || "pending",
      })),
      circuits: circuits.map((item) => ({
        id: item.id,
        name: item.name,
        family: item.family,
        confidence: item.confidence,
        status: item.status || "pending",
      })),
    },
  };
}
