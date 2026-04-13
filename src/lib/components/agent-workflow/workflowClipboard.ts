import { get } from 'svelte/store';
import { addEdge } from '@xyflow/svelte';
import type { Edge, Node } from '@xyflow/svelte';
import { edges, nodes } from './workflowStore';
import { pushUndoSnapshot } from './workflowHistory';

export type ClipboardPayload = {
	nodes: Node[];
	edges: Edge[];
};

let clipboard: ClipboardPayload | null = null;

export function copySubgraphToClipboard(nodeIds: string[]) {
	const idSet = new Set(nodeIds);
	if (idSet.size === 0) return;
	const subNodes = get(nodes).filter((n) => idSet.has(n.id));
	const subEdges = get(edges).filter((e) => idSet.has(e.source) && idSet.has(e.target));
	clipboard = {
		nodes: JSON.parse(JSON.stringify(subNodes)) as Node[],
		edges: JSON.parse(JSON.stringify(subEdges)) as Edge[]
	};
}

export function hasClipboard(): boolean {
	return clipboard != null && (clipboard?.nodes.length ?? 0) > 0;
}

/** Paste cloned subgraph with new ids at flow-space anchor (top-left + offset). */
export function pasteClipboardAt(flowPos: { x: number; y: number }): boolean {
	if (!clipboard || clipboard.nodes.length === 0) return false;
	pushUndoSnapshot();

	const idMap = new Map<string, string>();
	for (const n of clipboard.nodes) {
		idMap.set(n.id, crypto.randomUUID());
	}

	let minX = Infinity;
	let minY = Infinity;
	for (const n of clipboard.nodes) {
		minX = Math.min(minX, n.position.x);
		minY = Math.min(minY, n.position.y);
	}
	const dx = flowPos.x - minX;
	const dy = flowPos.y - minY;

	const newNodes: Node[] = clipboard.nodes.map((n) => {
		const raw = JSON.parse(JSON.stringify(n)) as Node;
		const nid = idMap.get(n.id)!;
		return {
			...raw,
			id: nid,
			position: { x: raw.position.x + dx, y: raw.position.y + dy },
			selected: false,
			dragging: false
		};
	});

	const newEdges: Edge[] = clipboard.edges.map((e) => {
		const raw = JSON.parse(JSON.stringify(e)) as Edge;
		return {
			...raw,
			id: `e-${crypto.randomUUID()}`,
			source: idMap.get(e.source)!,
			target: idMap.get(e.target)!,
			selected: false
		};
	});

	nodes.update((ns) => [...ns, ...newNodes]);
	edges.update((eds) => {
		let next = eds;
		for (const e of newEdges) {
			next = addEdge(
				{
					...e,
					type: e.type ?? 'workflow',
					animated: e.animated ?? true,
					selected: false
				},
				next
			);
		}
		return next;
	});
	return true;
}

export function duplicateNodesByIds(nodeIds: string[]): boolean {
	const idSet = new Set(nodeIds);
	if (idSet.size === 0) return false;
	pushUndoSnapshot();

	const selected = get(nodes).filter((n) => idSet.has(n.id));
	const idMap = new Map<string, string>();
	for (const n of selected) {
		idMap.set(n.id, crypto.randomUUID());
	}

	const offset = { x: 36, y: 36 };
	const newNodes: Node[] = selected.map((n) => {
		const raw = JSON.parse(JSON.stringify(n)) as Node;
		const nid = idMap.get(n.id)!;
		return {
			...raw,
			id: nid,
			position: { x: raw.position.x + offset.x, y: raw.position.y + offset.y },
			selected: true,
			dragging: false
		};
	});

	const innerEdges = get(edges).filter((e) => idSet.has(e.source) && idSet.has(e.target));
	const newEdges: Edge[] = innerEdges.map((e) => {
		const raw = JSON.parse(JSON.stringify(e)) as Edge;
		return {
			...raw,
			id: `e-${crypto.randomUUID()}`,
			source: idMap.get(e.source)!,
			target: idMap.get(e.target)!,
			selected: false
		};
	});

	nodes.update((ns) => [...ns.map((n) => ({ ...n, selected: false })), ...newNodes]);
	edges.update((eds) => {
		let next = eds.map((e) => ({ ...e, selected: false }));
		for (const e of newEdges) {
			next = addEdge(
				{
					...e,
					type: e.type ?? 'workflow',
					animated: e.animated ?? true,
					selected: false
				},
				next
			);
		}
		return next;
	});
	return true;
}
