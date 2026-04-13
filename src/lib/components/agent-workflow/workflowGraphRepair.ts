import type { AgentWorkflowV1, WorkflowNodeKind } from './types';

function nk(n: { nodeType?: WorkflowNodeKind }): WorkflowNodeKind {
	return n.nodeType ?? 'agent';
}

function newEdgeId(): string {
	if (typeof crypto !== 'undefined' && crypto.randomUUID) {
		return `e-ai-${crypto.randomUUID()}`;
	}
	return `e-ai-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/**
 * Fixes common LLM mistakes: wrong startNodeId (not trigger), missing edges in a linear chain.
 * Skips when IF or Merge nodes exist (branching / multi-input must stay LLM-accurate).
 */
export function repairWorkflowReachability(wf: AgentWorkflowV1): AgentWorkflowV1 {
	const nodeIds = new Set(wf.nodes.map((n) => n.id));
	const triggers = wf.nodes.filter((n) => nk(n) === 'trigger');
	if (triggers.length === 0) {
		return wf;
	}

	const hasBranching = wf.nodes.some((n) => nk(n) === 'if_else' || nk(n) === 'merge');
	if (hasBranching) {
		const t = triggers.sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0))[0];
		if (t && wf.startNodeId !== t.id) {
			return { ...wf, startNodeId: t.id };
		}
		return wf;
	}

	const trigger = triggers.sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0))[0];
	let startId = wf.startNodeId;
	if (!nodeIds.has(startId) || nk(wf.nodes.find((x) => x.id === startId)!) !== 'trigger') {
		startId = trigger.id;
	}

	const edges = wf.edges.filter((e) => nodeIds.has(e.fromNodeId) && nodeIds.has(e.toNodeId));
	const key = (a: string, b: string) => `${a}\0${b}`;
	const seen = new Set(edges.map((e) => key(e.fromNodeId, e.toNodeId)));

	const reachable = new Set<string>();
	const dq = [startId];
	while (dq.length) {
		const u = dq.shift()!;
		if (reachable.has(u)) continue;
		reachable.add(u);
		for (const e of edges) {
			if (e.fromNodeId === u) dq.push(e.toNodeId);
		}
	}

	const executable = wf.nodes.filter((n) => nk(n) !== 'group');
	const unreachable = executable.map((n) => n.id).filter((id) => !reachable.has(id));
	if (unreachable.length === 0) {
		return { ...wf, startNodeId: startId, edges };
	}

	let attach = startId;
	let maxX = -Infinity;
	for (const id of reachable) {
		const n = wf.nodes.find((x) => x.id === id);
		if (!n || nk(n) === 'group') continue;
		const x = n.position?.x ?? 0;
		if (x >= maxX) {
			maxX = x;
			attach = id;
		}
	}

	unreachable.sort((ida, idb) => {
		const a = wf.nodes.find((x) => x.id === ida)!;
		const b = wf.nodes.find((x) => x.id === idb)!;
		const dx = (a.position?.x ?? 0) - (b.position?.x ?? 0);
		if (dx !== 0) return dx;
		return (a.position?.y ?? 0) - (b.position?.y ?? 0);
	});

	const out = [...edges];
	const add = (from: string, to: string) => {
		if (from === to) return;
		const k = key(from, to);
		if (seen.has(k)) return;
		seen.add(k);
		out.push({
			id: newEdgeId(),
			fromNodeId: from,
			toNodeId: to
		});
	};

	add(attach, unreachable[0]);
	for (let i = 0; i < unreachable.length - 1; i++) {
		add(unreachable[i], unreachable[i + 1]);
	}

	return {
		...wf,
		startNodeId: startId,
		edges: out
	};
}
