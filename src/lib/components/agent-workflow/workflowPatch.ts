/**
 * Patch-based workflow edits (n8n-style): operations applied on top of current graph.
 * Execution engine unchanged — still consumes full AgentWorkflowV1 after apply.
 */

import type { AgentWorkflowEdgeV1, AgentWorkflowNodeV1, AgentWorkflowV1, WorkflowNodeKind } from './types';
import { validateAgentWorkflow } from './validate';
import { coerceWorkflowNodeType } from './workflowNodeTypeCoercion';

/** Single incremental change. Order matters. */
export type WorkflowOperation =
	| { type: 'add_node'; node: AgentWorkflowNodeV1 }
	| { type: 'update_node'; nodeId: string; changes: Partial<AgentWorkflowNodeV1> }
	| { type: 'remove_node'; nodeId: string }
	| { type: 'add_edge'; edge: AgentWorkflowEdgeV1 }
	| { type: 'remove_edge'; edgeId: string }
	| { type: 'set_start_node'; startNodeId: string };

/** LLM response envelope (PATCH-based). */
export type WorkflowPatchEnvelope = {
	operations: WorkflowOperation[];
	/** Optional: full graph for cross-check — not applied by applyOperations (use operations only). */
	previewWorkflow?: AgentWorkflowV1;
};

function cloneWorkflow(wf: AgentWorkflowV1): AgentWorkflowV1 {
	return JSON.parse(JSON.stringify(wf)) as AgentWorkflowV1;
}

function isPlainObject(v: unknown): v is Record<string, unknown> {
	return v !== null && typeof v === 'object' && !Array.isArray(v);
}

function normalizeNewNode(n: AgentWorkflowNodeV1): AgentWorkflowNodeV1 {
	const nt = coerceWorkflowNodeType(n as unknown as Record<string, unknown>, n.id);
	const base: AgentWorkflowNodeV1 = {
		...n,
		nodeType: nt,
		id: n.id,
		agentId: nt === 'group' ? n.agentId || n.id : (n.agentId || '').trim() || n.id,
		position: n.position ?? { x: 0, y: 0 }
	};
	if (nt === 'agent' && base.agentId !== base.id) {
		base.agentId = base.id;
	}
	return base;
}

function mergeNodeUpdate(
	target: AgentWorkflowNodeV1,
	changes: Partial<AgentWorkflowNodeV1>
): AgentWorkflowNodeV1 {
	const { id: _ignoreId, agentId: _ignoreAid, ...rest } = changes;
	let next: AgentWorkflowNodeV1 = {
		...target,
		...rest,
		id: target.id,
		agentId: target.nodeType === 'agent' ? target.id : target.agentId
	};
	if (changes.position) {
		next.position = { ...target.position, ...changes.position };
	}
	if (changes.config !== undefined) {
		const tc = target.config ?? {};
		const cc = changes.config;
		next.config = isPlainObject(tc) && isPlainObject(cc) ? { ...tc, ...cc } : cc;
	}
	return next;
}

export type ApplyOperationsResult =
	| { ok: true; workflow: AgentWorkflowV1 }
	| { ok: false; error: string };

type EdgeApply = 'applied' | 'deferred';

function tryApplyAddEdgeNow(
	wf: AgentWorkflowV1,
	nodeIds: Set<string>,
	edgeById: Map<string, AgentWorkflowEdgeV1>,
	e: AgentWorkflowEdgeV1
): EdgeApply | { err: string } {
	if (!e?.id || !e.fromNodeId || !e.toNodeId) {
		return { err: 'add_edge_invalid_shape' };
	}
	if (!nodeIds.has(e.fromNodeId) || !nodeIds.has(e.toNodeId)) {
		return 'deferred';
	}
	if (edgeById.has(e.id)) {
		return { err: `duplicate_edge_id:${e.id}` };
	}
	if (wf.edges.some((x) => x.fromNodeId === e.fromNodeId && x.toNodeId === e.toNodeId)) {
		return { err: 'add_edge_parallel_exists' };
	}
	wf.edges.push({ ...e });
	edgeById.set(e.id, e);
	return 'applied';
}

/**
 * Applies operations in order on a clone of `base`.
 * `add_edge` is deferred if endpoints do not exist yet (LLM often lists edges before new nodes); flushed in extra passes.
 * On any error, returns `{ ok: false }` — caller must not replace canvas.
 */
export function applyOperations(base: AgentWorkflowV1, operations: WorkflowOperation[]): ApplyOperationsResult {
	const wf = cloneWorkflow(base);
	const nodeIds = new Set(wf.nodes.map((n) => n.id));
	const edgeById = new Map(wf.edges.map((e) => [e.id, e]));
	const deferredEdges: AgentWorkflowEdgeV1[] = [];

	for (let i = 0; i < operations.length; i++) {
		const op = operations[i];
		if (!op || typeof op !== 'object' || !('type' in op)) {
			return { ok: false, error: `invalid_operation_at_index:${i}` };
		}
		switch (op.type) {
			case 'add_node': {
				const n = normalizeNewNode(op.node);
				if (!n.id?.trim()) {
					return { ok: false, error: 'add_node_missing_id' };
				}
				if (nodeIds.has(n.id)) {
					return { ok: false, error: `duplicate_node_id:${n.id}` };
				}
				wf.nodes.push(n);
				nodeIds.add(n.id);
				break;
			}
			case 'update_node': {
				const idx = wf.nodes.findIndex((x) => x.id === op.nodeId);
				if (idx < 0) {
					return { ok: false, error: `update_node_unknown:${op.nodeId}` };
				}
				wf.nodes[idx] = mergeNodeUpdate(wf.nodes[idx], op.changes ?? {});
				break;
			}
			case 'remove_node': {
				if (!nodeIds.has(op.nodeId)) {
					return { ok: false, error: `remove_node_unknown:${op.nodeId}` };
				}
				wf.nodes = wf.nodes.filter((n) => n.id !== op.nodeId);
				nodeIds.delete(op.nodeId);
				wf.edges = wf.edges.filter(
					(e) => e.fromNodeId !== op.nodeId && e.toNodeId !== op.nodeId
				);
				edgeById.clear();
				for (const e of wf.edges) edgeById.set(e.id, e);
				if (wf.startNodeId === op.nodeId) {
					return { ok: false, error: 'remove_node_cannot_remove_start_without_set_start' };
				}
				break;
			}
			case 'add_edge': {
				const r = tryApplyAddEdgeNow(wf, nodeIds, edgeById, op.edge);
				if (r === 'deferred') {
					deferredEdges.push(op.edge);
					break;
				}
				if (typeof r === 'object' && 'err' in r) {
					return { ok: false, error: r.err };
				}
				break;
			}
			case 'remove_edge': {
				const before = wf.edges.length;
				wf.edges = wf.edges.filter((e) => e.id !== op.edgeId);
				if (wf.edges.length === before) {
					return { ok: false, error: `remove_edge_unknown:${op.edgeId}` };
				}
				edgeById.delete(op.edgeId);
				break;
			}
			case 'set_start_node': {
				if (!nodeIds.has(op.startNodeId)) {
					return { ok: false, error: `set_start_unknown:${op.startNodeId}` };
				}
				wf.startNodeId = op.startNodeId;
				break;
			}
			default:
				return { ok: false, error: `unknown_operation_type:${(op as { type: string }).type}` };
		}
	}

	while (deferredEdges.length > 0) {
		const before = deferredEdges.length;
		const still: AgentWorkflowEdgeV1[] = [];
		for (const e of deferredEdges) {
			const r = tryApplyAddEdgeNow(wf, nodeIds, edgeById, e);
			if (r === 'deferred') {
				still.push(e);
			} else if (typeof r === 'object' && 'err' in r) {
				return { ok: false, error: r.err };
			}
		}
		if (still.length === before) {
			return { ok: false, error: 'add_edge_unknown_endpoint' };
		}
		deferredEdges.length = 0;
		deferredEdges.push(...still);
	}

	const v = validateAgentWorkflow(wf);
	if (v) {
		return { ok: false, error: `validation:${v}` };
	}
	return { ok: true, workflow: wf };
}

/** Structural check before apply (no full DAG validation). */
export function isWorkflowOperationList(v: unknown): v is WorkflowOperation[] {
	if (!Array.isArray(v)) return false;
	for (const x of v) {
		if (!x || typeof x !== 'object' || !('type' in x)) return false;
	}
	return true;
}
