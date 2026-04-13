import { get, writable } from 'svelte/store';
import type { Edge, Node } from '@xyflow/svelte';
import { edges, nodes, startNodeId } from './workflowStore';

const MAX_HISTORY = 50;

const past: string[] = [];
const future: string[] = [];

let applying = false;

export const canUndoStore = writable(false);
export const canRedoStore = writable(false);

function syncFlags() {
	canUndoStore.set(past.length > 0);
	canRedoStore.set(future.length > 0);
}

function serialize(): string {
	return JSON.stringify({
		nodes: get(nodes) as Node[],
		edges: get(edges) as Edge[],
		start: get(startNodeId)
	});
}

function deserialize(raw: string) {
	const o = JSON.parse(raw) as {
		nodes: Node[];
		edges: Edge[];
		start: string;
	};
	applying = true;
	try {
		nodes.set(o.nodes);
		edges.set(o.edges);
		startNodeId.set(o.start);
	} finally {
		applying = false;
	}
}

/** Call immediately before a structural mutation (add/remove/connect/duplicate/paste/import). */
export function pushUndoSnapshot() {
	if (applying) return;
	past.push(serialize());
	if (past.length > MAX_HISTORY) past.shift();
	future.length = 0;
	syncFlags();
}

export function clearWorkflowHistory() {
	past.length = 0;
	future.length = 0;
	syncFlags();
}

export function undoWorkflow(): boolean {
	if (past.length === 0) return false;
	future.push(serialize());
	deserialize(past.pop()!);
	syncFlags();
	return true;
}

export function redoWorkflow(): boolean {
	if (future.length === 0) return false;
	past.push(serialize());
	deserialize(future.pop()!);
	syncFlags();
	return true;
}

syncFlags();
