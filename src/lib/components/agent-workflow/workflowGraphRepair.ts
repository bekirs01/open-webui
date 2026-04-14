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

function newMergeNodeId(): string {
	if (typeof crypto !== 'undefined' && crypto.randomUUID) {
		return `m-ai-${crypto.randomUUID()}`;
	}
	return `m-ai-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

function edgeKey(from: string, to: string): string {
	return `${from}\0${to}`;
}

/**
 * LLMs often add BOTH trigger→branchNode AND if_else→branchNode. Branch nodes must have only
 * one parent (unless merge). Drop redundant trigger feeds when an if_else already feeds the node.
 */
export function stripRedundantTriggerFeed(wf: AgentWorkflowV1): AgentWorkflowV1 {
	const triggerIds = new Set(wf.nodes.filter((n) => nk(n) === 'trigger').map((n) => n.id));
	const ifIds = new Set(wf.nodes.filter((n) => nk(n) === 'if_else').map((n) => n.id));
	if (ifIds.size === 0 || triggerIds.size === 0) {
		return wf;
	}
	const dropEdgeIds = new Set<string>();
	for (const e of wf.edges) {
		if (!triggerIds.has(e.fromNodeId)) continue;
		const toId = e.toNodeId;
		const toNode = wf.nodes.find((x) => x.id === toId);
		if (!toNode) continue;
		const kind = nk(toNode);
		if (kind === 'merge' || kind === 'trigger' || kind === 'group') continue;
		const fedByIf = wf.edges.some((x) => x.toNodeId === toId && ifIds.has(x.fromNodeId));
		if (fedByIf) {
			dropEdgeIds.add(e.id);
		}
	}
	if (dropEdgeIds.size === 0) return wf;
	return {
		...wf,
		edges: wf.edges.filter((e) => !dropEdgeIds.has(e.id))
	};
}

function reachableFrom(
	startId: string,
	edges: AgentWorkflowV1['edges'],
	nodeIds: Set<string>
): Set<string> {
	const reachable = new Set<string>();
	const dq = [startId];
	while (dq.length) {
		const u = dq.shift()!;
		if (reachable.has(u)) continue;
		reachable.add(u);
		for (const e of edges) {
			if (!nodeIds.has(e.fromNodeId) || !nodeIds.has(e.toNodeId)) continue;
			if (e.fromNodeId === u) dq.push(e.toNodeId);
		}
	}
	return reachable;
}

/**
 * LLMs often emit if_else + branch agents but forget trigger→if_else or one branch edge.
 * Adds the minimum edges so every executable node can be reached from the trigger.
 */
function repairIfElseMissingEdges(wf: AgentWorkflowV1): AgentWorkflowV1 {
	const nodeIds = new Set(wf.nodes.map((n) => n.id));
	const triggers = wf.nodes.filter((n) => nk(n) === 'trigger').sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0));
	const ifNodes = wf.nodes.filter((n) => nk(n) === 'if_else').sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0));
	if (!triggers.length || !ifNodes.length) {
		return wf;
	}

	const triggerId = triggers[0].id;
	const ifId = ifNodes[0].id;
	let startId = wf.startNodeId;
	if (!nodeIds.has(startId) || nk(wf.nodes.find((x) => x.id === startId)!) !== 'trigger') {
		startId = triggerId;
	}

	let edges = wf.edges.filter((e) => nodeIds.has(e.fromNodeId) && nodeIds.has(e.toNodeId));
	const seen = new Set(edges.map((e) => edgeKey(e.fromNodeId, e.toNodeId)));
	const pushEdge = (from: string, to: string, sourceHandle?: string) => {
		const k = edgeKey(from, to);
		if (seen.has(k)) return;
		seen.add(k);
		edges.push({
			id: newEdgeId(),
			fromNodeId: from,
			toNodeId: to,
			...(sourceHandle ? { sourceHandle } : {})
		});
	};

	// 1) trigger → if_else (most common LLM omission)
	if (!edges.some((e) => e.fromNodeId === triggerId && e.toNodeId === ifId)) {
		pushEdge(triggerId, ifId);
	}

	let reachable = reachableFrom(startId, edges, nodeIds);

	const executableIds = wf.nodes.filter((n) => nk(n) !== 'group').map((n) => n.id);
	let unreachable = executableIds.filter((id) => !reachable.has(id));
	if (unreachable.length === 0) {
		return { ...wf, startNodeId: startId, edges };
	}

	// 2) if_else → branch targets: ensure true/false handles for orphan agents still off the graph
	const normHandle = (h: string | undefined) => (h ?? '').toLowerCase();

	const incomingCount = new Map<string, number>();
	for (const e of edges) {
		if (!nodeIds.has(e.fromNodeId) || !nodeIds.has(e.toNodeId)) continue;
		incomingCount.set(e.toNodeId, (incomingCount.get(e.toNodeId) ?? 0) + 1);
	}

	const orphanBranchTargets = unreachable
		.filter((id) => {
			const k = nk(wf.nodes.find((x) => x.id === id)!);
			return (
				(k === 'agent' ||
					k === 'transform' ||
					k === 'http_request' ||
					k === 'telegram') &&
				(incomingCount.get(id) ?? 0) === 0
			);
		})
		.sort((ida, idb) => {
			const a = wf.nodes.find((x) => x.id === ida)!;
			const b = wf.nodes.find((x) => x.id === idb)!;
			const dy = (a.position?.y ?? 0) - (b.position?.y ?? 0);
			if (dy !== 0) return dy;
			return (a.position?.x ?? 0) - (b.position?.x ?? 0);
		});

	if (!reachable.has(ifId)) {
		return { ...wf, startNodeId: startId, edges };
	}

	for (const aid of orphanBranchTargets) {
		const o = edges.filter((e) => e.fromNodeId === ifId);
		const ht = o.some((e) => normHandle(e.sourceHandle) === 'true');
		const hf = o.some((e) => normHandle(e.sourceHandle) === 'false');
		if (o.length >= 2 && ht && hf) {
			break;
		}
		if (!ht) {
			pushEdge(ifId, aid, 'true');
			continue;
		}
		if (!hf) {
			pushEdge(ifId, aid, 'false');
			continue;
		}
		break;
	}

	reachable = reachableFrom(startId, edges, nodeIds);
	unreachable = executableIds.filter((id) => !reachable.has(id));
	if (unreachable.length === 0) {
		return { ...wf, startNodeId: startId, edges };
	}

	// 3) last resort: linear chain from rightmost reachable node (keeps merge/if edge cases simpler)
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
	const seen2 = new Set(out.map((e) => edgeKey(e.fromNodeId, e.toNodeId)));
	const add = (from: string, to: string) => {
		if (from === to) return;
		const k = edgeKey(from, to);
		if (seen2.has(k)) return;
		seen2.add(k);
		out.push({ id: newEdgeId(), fromNodeId: from, toNodeId: to });
	};
	add(attach, unreachable[0]);
	for (let i = 0; i < unreachable.length - 1; i++) {
		add(unreachable[i], unreachable[i + 1]);
	}

	return { ...wf, startNodeId: startId, edges: out };
}

/**
 * LLMs often wire two branch outputs into one telegram/agent without a merge node.
 * For each non-merge executable node with 2+ incoming edges, inserts a merge node and rewires.
 */
export function repairMultipleIncomingWithMerge(wf: AgentWorkflowV1): AgentWorkflowV1 {
	const nodeIds = new Set(wf.nodes.map((n) => n.id));
	let nodes = [...wf.nodes];
	let edges = wf.edges.filter((e) => nodeIds.has(e.fromNodeId) && nodeIds.has(e.toNodeId));

	const incomingEdgesTo = (toId: string) => edges.filter((e) => e.toNodeId === toId);

	for (let pass = 0; pass < 8; pass++) {
		const incomingCount = new Map<string, number>();
		for (const e of edges) {
			incomingCount.set(e.toNodeId, (incomingCount.get(e.toNodeId) ?? 0) + 1);
		}

		const offenders: string[] = [];
		for (const n of nodes) {
			if (n.id === wf.startNodeId) continue;
			const kind = nk(n);
			if (kind === 'merge' || kind === 'group') continue;
			if ((incomingCount.get(n.id) ?? 0) <= 1) continue;
			offenders.push(n.id);
		}
		if (offenders.length === 0) break;

		offenders.sort();
		const victimId = offenders[0];
		const victim = nodes.find((x) => x.id === victimId);
		if (!victim) break;

		const ins = incomingEdgesTo(victimId);
		if (ins.length < 2) break;

		const mergeId = newMergeNodeId();
		const xs = ins.map((e) => nodes.find((x) => x.id === e.fromNodeId)?.position?.x ?? 0);
		const ys = ins.map((e) => nodes.find((x) => x.id === e.fromNodeId)?.position?.y ?? 0);
		const vx = victim.position?.x ?? 0;
		const vy = victim.position?.y ?? 0;
		const mx =
			(xs.reduce((a, b) => a + b, 0) / Math.max(1, xs.length) + vx) / 2 - 40;
		const my = (ys.reduce((a, b) => a + b, 0) / Math.max(1, ys.length) + vy) / 2;

		const mergeNode: (typeof nodes)[0] = {
			id: mergeId,
			nodeType: 'merge',
			agentId: mergeId,
			task: '',
			position: { x: mx, y: my },
			config: { separator: '\n---\n' }
		};
		nodes.push(mergeNode);

		const kept = edges.filter((e) => e.toNodeId !== victimId);
		const rebuilt = [...kept];
		for (const e of ins) {
			rebuilt.push({
				id: newEdgeId(),
				fromNodeId: e.fromNodeId,
				toNodeId: mergeId,
				when: 'always'
			});
		}
		rebuilt.push({
			id: newEdgeId(),
			fromNodeId: mergeId,
			toNodeId: victimId,
			when: 'always'
		});
		edges = rebuilt;
	}

	return { ...wf, nodes, edges };
}

/**
 * Fixes common LLM mistakes: wrong startNodeId (not trigger), missing edges in a linear chain.
 * For if_else graphs, also adds missing trigger→if and if→branch edges when the model omits them.
 */
export function repairWorkflowReachability(wf: AgentWorkflowV1): AgentWorkflowV1 {
	const nodeIds = new Set(wf.nodes.map((n) => n.id));
	const triggers = wf.nodes.filter((n) => nk(n) === 'trigger');
	if (triggers.length === 0) {
		return wf;
	}

	const hasIfElse = wf.nodes.some((n) => nk(n) === 'if_else');
	const hasMerge = wf.nodes.some((n) => nk(n) === 'merge');
	if (hasIfElse) {
		const t = triggers.sort((a, b) => (a.position?.x ?? 0) - (b.position?.x ?? 0))[0];
		let next = wf;
		if (t && wf.startNodeId !== t.id) {
			next = { ...wf, startNodeId: t.id };
		}
		return stripRedundantTriggerFeed(repairIfElseMissingEdges(next));
	}
	if (hasMerge) {
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
