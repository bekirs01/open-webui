/**
 * LLMs often omit "nodeType" or use alternate keys ("type", "kind") or XYFlow names ("ifElse").
 * normalizeWorkflowForLoad used to default missing nodeType to "agent", turning entire graphs into agents.
 */

import type { WorkflowNodeKind } from './types';

const LOWER_MAP: Record<string, WorkflowNodeKind> = {
	trigger: 'trigger',
	if_else: 'if_else',
	ifelse: 'if_else',
	if: 'if_else',
	if_else_node: 'if_else',
	conditional: 'if_else',
	transform: 'transform',
	transformer: 'transform',
	http_request: 'http_request',
	httprequest: 'http_request',
	telegram: 'telegram',
	/** Legacy: Google Sheets node removed — open old graphs as transform passthrough. */
	google_sheets: 'transform',
	google_sheets_node: 'transform',
	googlesheets: 'transform',
	merge: 'merge',
	group: 'group',
	agent: 'agent'
};

function normalizeKey(s: string): string {
	return s
		.trim()
		.toLowerCase()
		.replace(/\s+/g, '_')
		.replace(/-/g, '_');
}

/** Map values like "IF", "IfElse", "httpRequest" */
function mapStringToKind(s: string): WorkflowNodeKind | null {
	const k = normalizeKey(s);
	if (LOWER_MAP[k]) return LOWER_MAP[k];
	return null;
}

function readAlternateTypeFields(raw: Record<string, unknown>): unknown[] {
	return [
		raw.nodeType,
		raw.NodeType,
		raw.kind,
		raw.Kind,
		raw.type,
		raw.Type,
		raw.blockType,
		raw.BlockType,
		raw.blockKind,
		raw.node_type,
		raw.node_kind,
		(raw as { node?: { type?: unknown; kind?: unknown } }).node?.type,
		(raw as { node?: { type?: unknown; kind?: unknown } }).node?.kind
	];
}

/** Infer from common id prefixes when the model used UUIDs and forgot nodeType. */
function inferKindFromId(nodeId: string): WorkflowNodeKind | null {
	const id = nodeId.toLowerCase();
	if (/\btrigger\b/.test(id) || /^trig[-_]?/i.test(nodeId)) return 'trigger';
	if (/\bif_else\b|\bifelse\b|[-_]if[-_]?|\/if\d/i.test(id)) return 'if_else';
	if (/\btransform\b|trans_true|trans_false|branch_true|branch_false/i.test(id)) return 'transform';
	if (/(^|[-_])http[-_]|httpbin|_get_|webhook|fetch_req/i.test(id)) return 'http_request';
	if (/\btelegram\b|tg_send|botfather/i.test(id)) return 'telegram';
	return null;
}

/**
 * Resolves workflow node kind from LLM JSON. Falls back to "agent" only when nothing matches.
 */
export function coerceWorkflowNodeType(raw: Record<string, unknown>, nodeId: string): WorkflowNodeKind {
	for (const c of readAlternateTypeFields(raw)) {
		if (typeof c === 'string') {
			const m = mapStringToKind(c);
			if (m) return m;
		}
	}
	const inferred = inferKindFromId(nodeId);
	if (inferred) return inferred;
	return 'agent';
}
