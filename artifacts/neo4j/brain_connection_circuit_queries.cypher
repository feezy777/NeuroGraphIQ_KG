// NeuroGraphIQ KG - Neo4j query set for brain regions, connections, and circuits.
// Requires graph imported by scripts/db/export_to_neo4j.py.

// =========================================================
// 1) List regions and hierarchy by granularity
// =========================================================
:param granularity => 'all';  // all | major | sub | allen

MATCH (r)
WHERE
  ($granularity = 'all')
  OR ($granularity = 'major' AND r:MajorRegion)
  OR ($granularity = 'sub' AND r:SubRegion)
  OR ($granularity = 'allen' AND r:AllenRegion)
OPTIONAL MATCH (r)-[:SUB_REGION_OF]->(major:MajorRegion)
OPTIONAL MATCH (r)-[:ALLEN_REGION_OF]->(sub:SubRegion)
RETURN
  labels(r) AS labels,
  coalesce(r.major_region_id, r.sub_region_id, r.allen_region_id) AS region_id,
  r.region_code AS region_code,
  coalesce(r.cn_name, r.en_name) AS region_name,
  major.major_region_id AS parent_major_region_id,
  sub.sub_region_id AS parent_sub_region_id
ORDER BY labels, region_code;


// =========================================================
// 2) Upstream/Downstream connections for a region
// =========================================================
:param region_code => 'CHAIN_SUB_REGION_E6B727C4';

MATCH (r {region_code: $region_code})
WHERE r:MajorRegion OR r:SubRegion OR r:AllenRegion
OPTIONAL MATCH (in_conn)-[:TARGET_REGION]->(r)
OPTIONAL MATCH (in_conn)-[:SOURCE_REGION]->(in_src)
OPTIONAL MATCH (out_conn)-[:SOURCE_REGION]->(r)
OPTIONAL MATCH (out_conn)-[:TARGET_REGION]->(out_tgt)
RETURN
  r.region_code AS region_code,
  collect(distinct {
    direction: 'IN',
    connection_id: coalesce(in_conn.major_connection_id, in_conn.sub_connection_id, in_conn.allen_connection_id),
    connection_code: in_conn.connection_code,
    from_region_code: in_src.region_code,
    confidence: in_conn.confidence
  }) AS upstream_connections,
  collect(distinct {
    direction: 'OUT',
    connection_id: coalesce(out_conn.major_connection_id, out_conn.sub_connection_id, out_conn.allen_connection_id),
    connection_code: out_conn.connection_code,
    to_region_code: out_tgt.region_code,
    confidence: out_conn.confidence
  }) AS downstream_connections;


// =========================================================
// 3) Path between two regions (bounded hops through connections)
// =========================================================
:param from_region_code => 'CHAIN_MAJOR_REGION_A8C5D005';
:param to_region_code => 'CASE_ALLEN_70954673';
:param max_rel_depth => 12; // relationship steps, not region hops

MATCH (start {region_code: $from_region_code}), (end {region_code: $to_region_code})
WHERE (start:MajorRegion OR start:SubRegion OR start:AllenRegion)
  AND (end:MajorRegion OR end:SubRegion OR end:AllenRegion)
MATCH p = shortestPath((start)-[:SOURCE_REGION|TARGET_REGION*]-(end))
WHERE length(p) <= $max_rel_depth
RETURN p;


// =========================================================
// 4) Circuits associated with a region, including node order
// =========================================================
:param region_code => 'CHAIN_ALLEN_REGION_89273CAB';

MATCH (r {region_code: $region_code})
WHERE r:MajorRegion OR r:SubRegion OR r:AllenRegion
OPTIONAL MATCH (c)-[hn:HAS_NODE]->(r)
WHERE c:MajorCircuit OR c:SubCircuit OR c:AllenCircuit
RETURN
  labels(c) AS circuit_labels,
  coalesce(c.major_circuit_id, c.sub_circuit_id, c.allen_circuit_id) AS circuit_id,
  c.circuit_code AS circuit_code,
  coalesce(c.cn_name, c.en_name) AS circuit_name,
  hn.node_order AS node_order,
  hn.role_label AS role_label,
  c.circuit_kind AS circuit_kind,
  c.loop_type AS loop_type,
  c.cycle_verified AS cycle_verified
ORDER BY circuit_code, node_order;


// =========================================================
// 5) Circuit loop check (cycle_verified + structural hint)
// =========================================================
// Structural hint: there exists at least one reverse pair src->dst and dst->src
// among the included connections of the same circuit.
MATCH (c)
WHERE c:MajorCircuit OR c:SubCircuit OR c:AllenCircuit
OPTIONAL MATCH (c)-[:INCLUDES_CONNECTION]->(conn)
OPTIONAL MATCH (conn)-[:SOURCE_REGION]->(src)
OPTIONAL MATCH (conn)-[:TARGET_REGION]->(dst)
WITH c, collect({src: src, dst: dst}) AS edge_pairs
WITH
  c,
  size(edge_pairs) AS included_connection_count,
  any(e1 IN edge_pairs WHERE e1.src IS NOT NULL AND e1.dst IS NOT NULL AND any(e2 IN edge_pairs WHERE e2.src = e1.dst AND e2.dst = e1.src)) AS has_reverse_pair
RETURN
  labels(c) AS circuit_labels,
  coalesce(c.major_circuit_id, c.sub_circuit_id, c.allen_circuit_id) AS circuit_id,
  c.circuit_code AS circuit_code,
  c.cycle_verified AS cycle_verified_flag,
  has_reverse_pair AS structural_loop_hint,
  included_connection_count
ORDER BY circuit_code;


// =========================================================
// 6) Top-N connections by confidence
// =========================================================
:param granularity => 'all';  // all | major | sub | allen
:param top_n => 20;

MATCH (conn)
WHERE
  (conn:MajorConnection OR conn:SubConnection OR conn:AllenConnection)
  AND (
    $granularity = 'all'
    OR ($granularity = 'major' AND conn:MajorConnection)
    OR ($granularity = 'sub' AND conn:SubConnection)
    OR ($granularity = 'allen' AND conn:AllenConnection)
  )
OPTIONAL MATCH (conn)-[:SOURCE_REGION]->(src)
OPTIONAL MATCH (conn)-[:TARGET_REGION]->(dst)
RETURN
  labels(conn) AS connection_labels,
  coalesce(conn.major_connection_id, conn.sub_connection_id, conn.allen_connection_id) AS connection_id,
  conn.connection_code AS connection_code,
  src.region_code AS source_region_code,
  dst.region_code AS target_region_code,
  conn.connection_modality AS connection_modality,
  conn.confidence AS confidence
ORDER BY coalesce(conn.confidence, 0.0) DESC
LIMIT $top_n;
