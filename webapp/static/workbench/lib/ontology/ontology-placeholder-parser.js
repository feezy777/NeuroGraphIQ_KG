const RDF_NS = "http://www.w3.org/1999/02/22-rdf-syntax-ns#";
const RDFS_NS = "http://www.w3.org/2000/01/rdf-schema#";
const OWL_NS = "http://www.w3.org/2002/07/owl#";

function uniqueArray(values) {
  return [...new Set((values || []).filter(Boolean))];
}

function decodeXmlEntities(value) {
  return String(value || "")
    .replaceAll("&quot;", '"')
    .replaceAll("&apos;", "'")
    .replaceAll("&lt;", "<")
    .replaceAll("&gt;", ">")
    .replaceAll("&amp;", "&");
}

function normalizeIri(raw, namespace = "") {
  const iri = decodeXmlEntities(String(raw || "").trim()).replace(/^<|>$/g, "");
  if (!iri) return "";
  if (iri.startsWith("#")) {
    const base = namespace.replace(/#$/, "");
    return `${base}${iri}`;
  }
  return iri;
}

function labelFromIri(iri) {
  const normalized = normalizeIri(iri);
  if (!normalized) return "";
  const hash = normalized.lastIndexOf("#");
  const slash = normalized.lastIndexOf("/");
  const idx = Math.max(hash, slash);
  return idx >= 0 ? normalized.slice(idx + 1) : normalized;
}

function safeId(type, iri) {
  const label = labelFromIri(iri) || `${type}_${Math.random().toString(36).slice(2, 8)}`;
  return `${type}_${label}`.replace(/[^\w.-]+/g, "_");
}

function createEntity(type, iri, options = {}) {
  const normalizedIri = normalizeIri(iri, options.namespace || "");
  const fallbackLabel = labelFromIri(normalizedIri) || type;
  return {
    id: safeId(type, normalizedIri || fallbackLabel),
    type,
    label: decodeXmlEntities(options.label || fallbackLabel),
    iri: normalizedIri,
    parent: options.parent || "",
    description: decodeXmlEntities(options.description || ""),
    relations: uniqueArray(options.relations || []),
    constraints: uniqueArray(options.constraints || []),
    domain: uniqueArray(options.domain || []),
    range: uniqueArray(options.range || []),
  };
}

function mapSetEntity(map, entity) {
  if (!entity?.iri) return;
  if (map.has(entity.iri)) {
    const prev = map.get(entity.iri);
    map.set(entity.iri, {
      ...prev,
      ...entity,
      label: entity.label || prev.label,
      parent: entity.parent || prev.parent,
      description: entity.description || prev.description,
      relations: uniqueArray([...(prev.relations || []), ...(entity.relations || [])]),
      constraints: uniqueArray([...(prev.constraints || []), ...(entity.constraints || [])]),
      domain: uniqueArray([...(prev.domain || []), ...(entity.domain || [])]),
      range: uniqueArray([...(prev.range || []), ...(entity.range || [])]),
    });
    return;
  }
  map.set(entity.iri, entity);
}

function parsePrefixes(text) {
  const prefixes = [];
  const namespaceRegex = /xmlns:([\w-]+)="([^"]+)"/gi;
  const turtleRegex = /@prefix\s+([\w-]+):\s*<([^>]+)>/gi;
  let match;
  while ((match = namespaceRegex.exec(text))) prefixes.push(`${match[1]}=${match[2]}`);
  while ((match = turtleRegex.exec(text))) prefixes.push(`${match[1]}=${match[2]}`);
  return uniqueArray(prefixes);
}

function parseNamespace(text) {
  const xmlBase = text.match(/xml:base="([^"]+)"/i);
  if (xmlBase?.[1]) return xmlBase[1];
  const defaultNs = text.match(/xmlns="([^"]+)"/i);
  if (defaultNs?.[1]) return defaultNs[1];
  const defaultPrefix = text.match(/@prefix\s*:\s*<([^>]+)>/i);
  if (defaultPrefix?.[1]) return defaultPrefix[1];
  return "";
}

function readAttr(node, name, ns, local) {
  return (
    node.getAttribute(name) ||
    (ns && local ? node.getAttributeNS(ns, local) : "") ||
    ""
  );
}

function resourceFromNode(node, namespace) {
  const about = readAttr(node, "rdf:about", RDF_NS, "about");
  if (about) return normalizeIri(about, namespace);
  const id = readAttr(node, "rdf:ID", RDF_NS, "ID");
  if (id) {
    const base = namespace.replace(/#$/, "");
    return normalizeIri(`${base}#${id}`, namespace);
  }
  return "";
}

function directChildren(node) {
  return Array.from(node.children || []);
}

function directResources(node, namespaceUri, localName, namespace) {
  return uniqueArray(
    directChildren(node)
      .filter((child) => child.namespaceURI === namespaceUri && child.localName === localName)
      .map((child) => normalizeIri(readAttr(child, "rdf:resource", RDF_NS, "resource"), namespace))
      .filter(Boolean),
  );
}

function directText(node, namespaceUri, localName) {
  const target = directChildren(node).find(
    (child) => child.namespaceURI === namespaceUri && child.localName === localName,
  );
  return decodeXmlEntities(String(target?.textContent || "").trim());
}

function parseXmlOntology(text, namespaceHint) {
  if (typeof DOMParser === "undefined") return null;
  const parser = new DOMParser();
  const doc = parser.parseFromString(text, "application/xml");
  if (doc.getElementsByTagName("parsererror").length) return null;

  const xmlBase =
    doc.documentElement?.getAttribute("xml:base") ||
    doc.documentElement?.getAttributeNS("http://www.w3.org/XML/1998/namespace", "base") ||
    "";
  const namespace = namespaceHint || xmlBase || "";

  const classes = new Map();
  const objectProperties = new Map();
  const dataProperties = new Map();
  const individuals = new Map();
  const constraints = new Map();

  function pushConstraint(kind, childIri, parentIri) {
    const child = normalizeIri(childIri, namespace);
    const parent = normalizeIri(parentIri, namespace);
    if (!child || !parent) return;
    const constraintIri = `${child}::${kind}::${parent}`;
    mapSetEntity(
      constraints,
      createEntity("constraint", constraintIri, {
        label: `${kind}: ${labelFromIri(child)} -> ${labelFromIri(parent)}`,
        description: kind,
      }),
    );
  }

  function parseCommonEntity(type, node) {
    const iri = resourceFromNode(node, namespace);
    if (!iri) return null;
    const label = directText(node, RDFS_NS, "label");
    const description = directText(node, RDFS_NS, "comment");
    const domain = directResources(node, RDFS_NS, "domain", namespace);
    const range = directResources(node, RDFS_NS, "range", namespace);
    return { iri, label, description, domain, range, type };
  }

  function parseClass(node) {
    const common = parseCommonEntity("class", node);
    if (!common) return;
    const parents = directResources(node, RDFS_NS, "subClassOf", namespace);
    parents.forEach((parent) => pushConstraint("subClassOf", common.iri, parent));
    mapSetEntity(
      classes,
      createEntity("class", common.iri, {
        namespace,
        label: common.label || labelFromIri(common.iri),
        description: common.description,
        parent: parents[0] || "",
        domain: common.domain,
        range: common.range,
        constraints: parents.map((p) => `subClassOf:${p}`),
      }),
    );
  }

  function parseObjectProperty(node) {
    const common = parseCommonEntity("object_property", node);
    if (!common) return;
    const parents = directResources(node, RDFS_NS, "subPropertyOf", namespace);
    const inverseOf = directResources(node, OWL_NS, "inverseOf", namespace);
    parents.forEach((parent) => pushConstraint("subPropertyOf", common.iri, parent));
    mapSetEntity(
      objectProperties,
      createEntity("object_property", common.iri, {
        namespace,
        label: common.label || labelFromIri(common.iri),
        description: common.description,
        parent: parents[0] || "",
        domain: common.domain,
        range: common.range,
        relations: inverseOf.map((p) => `inverseOf:${p}`),
        constraints: [
          ...parents.map((p) => `subPropertyOf:${p}`),
          ...common.domain.map((p) => `domain:${p}`),
          ...common.range.map((p) => `range:${p}`),
        ],
      }),
    );
  }

  function parseDataProperty(node) {
    const common = parseCommonEntity("data_property", node);
    if (!common) return;
    const parents = directResources(node, RDFS_NS, "subPropertyOf", namespace);
    parents.forEach((parent) => pushConstraint("subPropertyOf", common.iri, parent));
    mapSetEntity(
      dataProperties,
      createEntity("data_property", common.iri, {
        namespace,
        label: common.label || labelFromIri(common.iri),
        description: common.description,
        parent: parents[0] || "",
        domain: common.domain,
        range: common.range,
        constraints: [
          ...parents.map((p) => `subPropertyOf:${p}`),
          ...common.domain.map((p) => `domain:${p}`),
          ...common.range.map((p) => `range:${p}`),
        ],
      }),
    );
  }

  function parseIndividual(node) {
    const common = parseCommonEntity("individual", node);
    if (!common) return;
    const types = directResources(node, RDF_NS, "type", namespace);
    const relations = [];
    for (const child of directChildren(node)) {
      const resource = normalizeIri(readAttr(child, "rdf:resource", RDF_NS, "resource"), namespace);
      if (!resource) continue;
      const relIri = `${child.namespaceURI || ""}${child.localName || ""}`;
      relations.push(`${labelFromIri(relIri) || child.localName}:${resource}`);
    }
    mapSetEntity(
      individuals,
      createEntity("individual", common.iri, {
        namespace,
        label: common.label || labelFromIri(common.iri),
        description: common.description,
        parent: types[0] || "",
        relations: [...types.map((t) => `rdf:type:${t}`), ...relations],
        constraints: [
          ...types.map((p) => `rdf:type:${p}`),
          ...common.domain.map((p) => `domain:${p}`),
          ...common.range.map((p) => `range:${p}`),
        ],
      }),
    );
  }

  Array.from(doc.getElementsByTagNameNS(OWL_NS, "Class")).forEach(parseClass);
  Array.from(doc.getElementsByTagNameNS(RDFS_NS, "Class")).forEach(parseClass);
  Array.from(doc.getElementsByTagNameNS(OWL_NS, "ObjectProperty")).forEach(parseObjectProperty);
  Array.from(doc.getElementsByTagNameNS(OWL_NS, "DatatypeProperty")).forEach(parseDataProperty);
  Array.from(doc.getElementsByTagNameNS(OWL_NS, "NamedIndividual")).forEach(parseIndividual);

  const rdfDescriptions = Array.from(doc.getElementsByTagNameNS(RDF_NS, "Description"));
  rdfDescriptions.forEach((node) => {
    const iri = resourceFromNode(node, namespace);
    if (!iri) return;
    const types = directResources(node, RDF_NS, "type", namespace);
    if (!types.length) return;

    const isClass = types.some((t) => t === `${OWL_NS}Class` || t === `${RDFS_NS}Class`);
    const isObjectProperty = types.includes(`${OWL_NS}ObjectProperty`);
    const isDataProperty = types.includes(`${OWL_NS}DatatypeProperty`);
    const isNamedIndividual = types.includes(`${OWL_NS}NamedIndividual`);
    const isSchemaType =
      isClass ||
      isObjectProperty ||
      isDataProperty ||
      isNamedIndividual;

    if (isClass) {
      parseClass(node);
      return;
    }
    if (isObjectProperty) {
      parseObjectProperty(node);
      return;
    }
    if (isDataProperty) {
      parseDataProperty(node);
      return;
    }
    if (isNamedIndividual || (!isSchemaType && types.length > 0)) {
      parseIndividual(node);
    }
  });

  return {
    classes: [...classes.values()],
    objectProperties: [...objectProperties.values()],
    dataProperties: [...dataProperties.values()],
    individuals: [...individuals.values()],
    constraints: [...constraints.values()],
  };
}

function parseTurtleLike(text, namespace) {
  const classes = new Map();
  const objectProperties = new Map();
  const dataProperties = new Map();
  const individuals = new Map();
  const constraints = new Map();

  const classRegex = /(^|\s)([^\s;]+)\s+a\s+owl:Class\b/gim;
  const rdfsClassRegex = /(^|\s)([^\s;]+)\s+a\s+rdfs:Class\b/gim;
  const objectRegex = /(^|\s)([^\s;]+)\s+a\s+owl:ObjectProperty\b/gim;
  const dataRegex = /(^|\s)([^\s;]+)\s+a\s+owl:DatatypeProperty\b/gim;
  const individualRegex = /(^|\s)([^\s;]+)\s+a\s+owl:NamedIndividual\b/gim;
  const subClassRegex = /([^\s;]+)\s+rdfs:subClassOf\s+([^\s;]+)/gim;
  const subPropertyRegex = /([^\s;]+)\s+rdfs:subPropertyOf\s+([^\s;]+)/gim;

  let match;
  while ((match = classRegex.exec(text))) {
    const iri = normalizeIri(match[2], namespace);
    mapSetEntity(classes, createEntity("class", iri, { label: labelFromIri(iri) }));
  }
  while ((match = rdfsClassRegex.exec(text))) {
    const iri = normalizeIri(match[2], namespace);
    mapSetEntity(classes, createEntity("class", iri, { label: labelFromIri(iri) }));
  }
  while ((match = objectRegex.exec(text))) {
    const iri = normalizeIri(match[2], namespace);
    mapSetEntity(objectProperties, createEntity("object_property", iri, { label: labelFromIri(iri) }));
  }
  while ((match = dataRegex.exec(text))) {
    const iri = normalizeIri(match[2], namespace);
    mapSetEntity(dataProperties, createEntity("data_property", iri, { label: labelFromIri(iri) }));
  }
  while ((match = individualRegex.exec(text))) {
    const iri = normalizeIri(match[2], namespace);
    mapSetEntity(individuals, createEntity("individual", iri, { label: labelFromIri(iri) }));
  }
  while ((match = subClassRegex.exec(text))) {
    const child = normalizeIri(match[1], namespace);
    const parent = normalizeIri(match[2], namespace);
    const iri = `${child}::subClassOf::${parent}`;
    mapSetEntity(
      constraints,
      createEntity("constraint", iri, {
        label: `subClassOf: ${labelFromIri(child)} -> ${labelFromIri(parent)}`,
        description: "subClassOf",
      }),
    );
  }
  while ((match = subPropertyRegex.exec(text))) {
    const child = normalizeIri(match[1], namespace);
    const parent = normalizeIri(match[2], namespace);
    const iri = `${child}::subPropertyOf::${parent}`;
    mapSetEntity(
      constraints,
      createEntity("constraint", iri, {
        label: `subPropertyOf: ${labelFromIri(child)} -> ${labelFromIri(parent)}`,
        description: "subPropertyOf",
      }),
    );
  }

  return {
    classes: [...classes.values()],
    objectProperties: [...objectProperties.values()],
    dataProperties: [...dataProperties.values()],
    individuals: [...individuals.values()],
    constraints: [...constraints.values()],
  };
}

function fallbackEntities() {
  return {
    classes: [
      createEntity("class", "BrainRegion"),
      createEntity("class", "ConnectionEntity"),
      createEntity("class", "CircuitEntity"),
      createEntity("class", "EvidenceEntity"),
    ],
    objectProperties: [
      createEntity("object_property", "has_source"),
      createEntity("object_property", "has_target"),
      createEntity("object_property", "has_node"),
      createEntity("object_property", "has_connection"),
    ],
    dataProperties: [createEntity("data_property", "confidence")],
    individuals: [],
    constraints: [createEntity("constraint", "brain_region_hierarchy", { description: "placeholder constraint" })],
  };
}

export function parseOntologyPlaceholder({ filename, fileType, text }) {
  const sourceText = String(text || "");
  const safeType = String(fileType || "").toLowerCase();
  const namespace = parseNamespace(sourceText);
  const isXmlLike = ["owl", "rdf", "xml"].includes(safeType);

  let parsed = null;
  if (isXmlLike) parsed = parseXmlOntology(sourceText, namespace);
  if (!parsed) parsed = parseTurtleLike(sourceText, namespace);

  const hasAny =
    (parsed?.classes?.length || 0) > 0 ||
    (parsed?.objectProperties?.length || 0) > 0 ||
    (parsed?.dataProperties?.length || 0) > 0 ||
    (parsed?.individuals?.length || 0) > 0 ||
    (parsed?.constraints?.length || 0) > 0;

  const entities = hasAny ? parsed : fallbackEntities();
  const prefixes = parsePrefixes(sourceText);

  return {
    meta: {
      ontologyName: filename || "ontology",
      fileType: fileType || "",
      namespace,
      prefixes,
      parseMode: hasAny ? (isXmlLike ? "rdf_dom_parser" : "ttl_regex_parser") : "placeholder_fallback",
    },
    stats: {
      classes: entities.classes.length,
      objectProperties: entities.objectProperties.length,
      dataProperties: entities.dataProperties.length,
      individuals: entities.individuals.length,
      constraints: entities.constraints.length,
    },
    entities,
  };
}

