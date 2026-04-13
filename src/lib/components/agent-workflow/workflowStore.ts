import { get, writable } from 'svelte/store';
import { addEdge } from '@xyflow/svelte';
import type { Connection, Edge, Node } from '@xyflow/svelte';
import { NODE_REGISTRY, type FlowNodeTypeId } from './nodeRegistry';

export const nodes = writable<Node[]>([]);
export const edges = writable<Edge[]>([]);
/** Entry node for execution — separate from node.data for fewer node updates. */
export const startNodeId = writable<string>('');

export function getDefaultDataForType(
	type: FlowNodeTypeId,
	defaultModelId: string
): Record<string, unknown> {
	const base = NODE_REGISTRY[type].defaultData;
	if (type === 'agent') {
		return {
			...base,
			modelId: (base.modelId as string) || defaultModelId
		};
	}
	return { ...base };
}

/** Merge new data into a single node — keeps other node references stable. */
export function updateNodeData(id: string, patch: Record<string, unknown>) {
	nodes.update((list) => {
		const i = list.findIndex((n) => n.id === id);
		if (i === -1) return list;
		const n = list[i];
		const nextData = { ...n.data, ...patch };
		let same = true;
		for (const k of Object.keys(nextData)) {
			if ((n.data as Record<string, unknown>)[k] !== (nextData as Record<string, unknown>)[k]) {
				same = false;
				break;
			}
		}
		if (same) return list;
		const next = list.slice();
		if (n.type === 'group' && ('width' in patch || 'height' in patch)) {
			const w = Number((nextData as { width?: number }).width) || 320;
			const h = Number((nextData as { height?: number }).height) || 220;
			next[i] = { ...n, data: nextData, style: `width: ${w}px; height: ${h}px;` };
		} else {
			next[i] = { ...n, data: nextData };
		}
		return next;
	});
}

export function setStartNode(id: string) {
	startNodeId.set(id);
}

export function createFlowNode(
	type: FlowNodeTypeId,
	id: string,
	position: { x: number; y: number },
	defaultModelId: string
): Node {
	const data = getDefaultDataForType(type, defaultModelId);
	if (type === 'group') {
		const w = Number((data as { width?: number }).width) || 320;
		const h = Number((data as { height?: number }).height) || 220;
		return {
			id,
			type,
			position,
			data,
			style: `width: ${w}px; height: ${h}px;`,
			class: 'agent-workflow-group-node',
			zIndex: -1
		};
	}
	return {
		id,
		type,
		position,
		data
	};
}

export function addNodeAt(
	type: FlowNodeTypeId,
	position: { x: number; y: number },
	defaultModelId: string,
	opts?: {
		connectFrom?: { source: string; sourceHandle?: string | null };
		makeStartIfEmpty?: boolean;
	}
): string {
	const id = crypto.randomUUID();
	const node = createFlowNode(type, id, position, defaultModelId);
	const list = get(nodes);
	const start = get(startNodeId);
	const isEmpty = list.length === 0;
	const shouldStart = opts?.makeStartIfEmpty !== false && (isEmpty || !start);

	nodes.update((ns) => [...ns, node]);

	if (shouldStart) {
		startNodeId.set(id);
	}

	if (opts?.connectFrom) {
		const { source, sourceHandle } = opts.connectFrom;
		edges.update((eds) =>
			addEdge(
				{
					id: `e-${crypto.randomUUID()}`,
					source,
					target: id,
					...(sourceHandle ? { sourceHandle } : {}),
					type: 'workflow',
					animated: true
				},
				eds
			)
		);
	}
	return id;
}

/** Remove edges connected to ids, then remove nodes. Fixes start if deleted. */
export function removeNodesById(ids: Set<string>) {
	if (ids.size === 0) return;
	nodes.update((ns) => ns.filter((n) => !ids.has(n.id)));
	edges.update((eds) => eds.filter((e) => !ids.has(e.source) && !ids.has(e.target)));
	const start = get(startNodeId);
	if (start && ids.has(start)) {
		const rest = get(nodes);
		startNodeId.set(rest[0]?.id ?? '');
	}
}

export function splitEdgeWithNewNode(
	edgeId: string,
	newNodeType: FlowNodeTypeId,
	position: { x: number; y: number },
	defaultModelId: string
): string | null {
	const e = get(edges).find((x) => x.id === edgeId);
	if (!e) return null;
	const newId = crypto.randomUUID();
	const node = createFlowNode(newNodeType, newId, position, defaultModelId);
	nodes.update((ns) => [...ns, node]);
	edges.update((eds) => {
		const rest = eds.filter((x) => x.id !== edgeId);
		const a = addEdge(
			{
				id: `e-${e.source}-${newId}-splita`,
				source: e.source,
				target: newId,
				...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
				type: 'workflow',
				animated: true
			},
			rest
		);
		return addEdge(
			{
				id: `e-${newId}-${e.target}-splitb`,
				source: newId,
				target: e.target,
				type: 'workflow',
				animated: true
			},
			a
		);
	});
	return newId;
}

/** Map agent field updates (typed). */
export function patchAgentNode(
	id: string,
	field: 'agentName' | 'modelId' | 'task' | 'mode',
	value: string
) {
	const next =
		field === 'mode' ? (value === 'image' ? 'image' : 'text') : value;
	updateNodeData(id, { [field]: next });
}

export function toggleNodeDisabled(id: string) {
	nodes.update((list) => {
		const i = list.findIndex((n) => n.id === id);
		if (i === -1) return list;
		const n = list[i];
		const d = { ...(n.data as Record<string, unknown>) };
		d.disabled = !Boolean(d.disabled);
		const next = list.slice();
		next[i] = { ...n, data: d };
		return next;
	});
}

export function toggleEdgeDisabled(edgeId: string) {
	edges.update((eds) =>
		eds.map((e) => {
			if (e.id !== edgeId) return e;
			const prev = (e.data as Record<string, unknown> | undefined) ?? {};
			return {
				...e,
				data: { ...prev, disabled: !Boolean(prev.disabled) }
			};
		})
	);
}
