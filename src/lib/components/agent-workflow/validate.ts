import type { AgentWorkflowV1, WorkflowNodeKind } from './types';

function nodeKind(n: { nodeType?: WorkflowNodeKind }): WorkflowNodeKind {
	return n.nodeType ?? 'agent';
}

/** Returns an error message key or null if the workflow can be executed. */
export function validateAgentWorkflow(wf: AgentWorkflowV1): string | null {
	if (!wf.nodes.length) {
		return 'add_at_least_one_node';
	}
	const nodeIds = new Set(wf.nodes.map((n) => n.id));
	if (!wf.startNodeId || !nodeIds.has(wf.startNodeId)) {
		return 'invalid_start_node';
	}

	for (const n of wf.nodes) {
		const kind = nodeKind(n);
		if (kind === 'group') {
			continue;
		}
		if (kind !== 'agent') {
			continue;
		}
		const aid = (n.agentId || '').trim();
		if (!aid || aid !== n.id) {
			return 'node_missing_agent';
		}
		if (!(n.modelId || '').trim()) {
			return 'agent_missing_model';
		}
	}

	const incomingToStart = wf.edges.filter(
		(e) => e.toNodeId === wf.startNodeId && nodeIds.has(e.fromNodeId)
	);
	if (incomingToStart.length) {
		return 'start_has_incoming';
	}

	const incomingCount = new Map<string, number>();
	const edgesInto = new Map<string, typeof wf.edges>();
	for (const e of wf.edges) {
		if (!nodeIds.has(e.fromNodeId) || !nodeIds.has(e.toNodeId)) continue;
		incomingCount.set(e.toNodeId, (incomingCount.get(e.toNodeId) ?? 0) + 1);
		if (!edgesInto.has(e.toNodeId)) edgesInto.set(e.toNodeId, []);
		edgesInto.get(e.toNodeId)!.push(e);
	}

	for (const n of wf.nodes) {
		const kind = nodeKind(n);
		if (n.id === wf.startNodeId) continue;
		const inc = incomingCount.get(n.id) ?? 0;
		if (kind === 'merge') {
			if (inc < 2) {
				return 'merge_needs_two_inputs';
			}
			for (const e of edgesInto.get(n.id) ?? []) {
				const w = e.when ?? 'always';
				if (w !== 'always') {
					return 'merge_edges_must_be_always';
				}
			}
			continue;
		}
		if (kind === 'group') {
			if (inc > 0) {
				return 'group_has_incoming';
			}
			continue;
		}
		if (inc > 1) {
			return 'multiple_incoming_not_supported';
		}
	}

	const outgoingCount = new Map<string, number>();
	for (const e of wf.edges) {
		if (!nodeIds.has(e.fromNodeId) || !nodeIds.has(e.toNodeId)) continue;
		outgoingCount.set(e.fromNodeId, (outgoingCount.get(e.fromNodeId) ?? 0) + 1);
	}

	for (const n of wf.nodes) {
		const kind = nodeKind(n);
		const outs = outgoingCount.get(n.id) ?? 0;
		if (kind === 'group' && outs > 0) {
			return 'group_has_outgoing';
		}
		if (kind === 'if_else') {
			if (outs > 2) {
				return 'if_too_many_outgoing';
			}
			continue;
		}
		if (kind === 'merge' && outs > 1) {
			return 'merge_too_many_outgoing';
		}
	}

	const adj = new Map<string, string[]>();
	for (const e of wf.edges) {
		if (!nodeIds.has(e.fromNodeId) || !nodeIds.has(e.toNodeId)) continue;
		const fromK = nodeKind(wf.nodes.find((x) => x.id === e.fromNodeId)!);
		const toK = nodeKind(wf.nodes.find((x) => x.id === e.toNodeId)!);
		if (fromK === 'group' || toK === 'group') {
			return 'group_has_edge';
		}
		if (!adj.has(e.fromNodeId)) adj.set(e.fromNodeId, []);
		adj.get(e.fromNodeId)!.push(e.toNodeId);
	}

	const reachable = new Set<string>();
	const dq = [wf.startNodeId];
	while (dq.length) {
		const u = dq.shift()!;
		if (reachable.has(u)) continue;
		reachable.add(u);
		for (const v of adj.get(u) ?? []) dq.push(v);
	}

	const executableIds = new Set(
		wf.nodes.filter((n) => nodeKind(n) !== 'group').map((n) => n.id)
	);
	for (const nid of executableIds) {
		if (!reachable.has(nid)) {
			return 'unreachable_nodes';
		}
	}

	const indeg = new Map<string, number>();
	for (const id of executableIds) {
		indeg.set(id, 0);
	}
	const subAdj = new Map<string, string[]>();
	for (const u of executableIds) {
		for (const v of adj.get(u) ?? []) {
			if (!executableIds.has(v)) continue;
			if (!subAdj.has(u)) subAdj.set(u, []);
			subAdj.get(u)!.push(v);
			indeg.set(v, (indeg.get(v) ?? 0) + 1);
		}
	}

	const roots = [...executableIds].filter((u) => (indeg.get(u) ?? 0) === 0).sort();
	if (!roots.includes(wf.startNodeId)) {
		return 'start_not_source';
	}

	const queue = [wf.startNodeId, ...roots.filter((r) => r !== wf.startNodeId)];
	const order: string[] = [];
	while (queue.length) {
		const u = queue.shift()!;
		order.push(u);
		for (const v of (subAdj.get(u) ?? []).sort()) {
			indeg.set(v, (indeg.get(v) ?? 0) - 1);
			if (indeg.get(v) === 0) queue.push(v);
		}
	}
	if (order.length !== executableIds.size) {
		return 'cycle';
	}
	return null;
}
