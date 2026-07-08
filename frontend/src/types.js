/**
 * @typedef {'capability'|'procedure'|'workflow'|'tool'|'repository'|'environment'|'dependency'|'data'|'analytical'|'memory'|'heuristic'|'constraint'|'generic'} EntryType
 */

/**
 * @typedef {'unverified'|'self_tested'|'peer_reviewed'|'community_tested'|'bugged'|'deprecated'} VerificationStatus
 */

/**
 * @typedef {Object} RemoteSource
 * @property {string=} url
 * @property {string=} kind
 * @property {string=} status
 * @property {string=} fetched_at
 * @property {string=} owner
 * @property {string=} repo
 * @property {string=} ref
 * @property {string=} path
 * @property {string=} last_error
 * @property {boolean=} auto_sync
 * @property {number=} sync_interval_seconds
 */

/**
 * @typedef {Object} EntryMetadata
 * @property {string=} refinement_status
 * @property {number=} trust_score
 * @property {number=} usage_count
 * @property {string=} source_provenance
 * @property {string=} extraction_method
 * @property {VerificationStatus=} verification_status
 * @property {number=} review_count
 * @property {RemoteSource=} remote_source
 * @property {string[]=} related_environments
 * @property {string[]=} runtime_requirements
 * @property {string[]=} external_refs
 * @property {Record<string, unknown>=} custom
 */

/**
 * @typedef {Object} EntryAsset
 * @property {string} folder
 * @property {string} filename
 * @property {string=} kind
 * @property {string=} language
 * @property {string=} mime_type
 * @property {string=} description
 * @property {string[]=} requirements
 * @property {number=} size
 * @property {string=} download_url
 */

/**
 * @typedef {Object} EntryScript
 * @property {string} filename
 * @property {string=} language
 * @property {string=} description
 * @property {string[]=} requirements
 */

/**
 * @typedef {Object} GraphNode
 * @property {string} id
 * @property {string=} slug
 * @property {string=} title
 * @property {EntryType|string=} entry_type
 * @property {string=} content
 * @property {string[]=} tags
 * @property {string[]=} aliases
 * @property {EntryMetadata=} metadata
 * @property {EntryAsset[]=} assets
 * @property {EntryScript[]=} scripts
 * @property {string[]=} internal_refs
 * @property {number=} x
 * @property {number=} y
 * @property {number=} _score
 */

/**
 * @typedef {Object} GraphEdge
 * @property {string|GraphNode} source
 * @property {string|GraphNode} target
 * @property {string=} relation
 */

/**
 * @typedef {Object} GraphPayload
 * @property {GraphNode[]} nodes
 * @property {GraphEdge[]} edges
 */

/**
 * @typedef {Object} UiState
 * @property {GraphNode[]} allNodes
 * @property {GraphEdge[]} allEdges
 * @property {string|null} selectedId
 * @property {boolean} showLabels
 * @property {string} colorMode
 * @property {Set<string>|null} apiMatchIds
 * @property {Record<string, number>} searchScores
 */

export {};
