import { writable } from 'svelte/store';

/** @deprecated Replay highlight — prefer runActiveNodeId + runPathNodeIds */
export const runStepHighlightId = writable<string | null>(null);

/** Currently executing node (live run / stream). */
export const runActiveNodeId = writable<string | null>(null);

/** Nodes on the taken path after run completes (persistent until next run). */
export const runPathNodeIds = writable<Set<string>>(new Set());

/** Edges on the taken path (consecutive pairs in execution order). */
export const runPathEdgeIds = writable<Set<string>>(new Set());

export function clearRunVisualization() {
	runStepHighlightId.set(null);
	runActiveNodeId.set(null);
	runPathNodeIds.set(new Set());
	runPathEdgeIds.set(new Set());
}

export type ContextMenuTarget =
	| { kind: 'node'; id: string; x: number; y: number }
	| { kind: 'edge'; id: string; x: number; y: number };

export const workflowContextMenu = writable<ContextMenuTarget | null>(null);

export type PendingConnection = {
	source: string;
	sourceHandle?: string | null;
};

/** Screen-space anchor for floating picker (optional). */
export const nodePickerScreenPos = writable<{ x: number; y: number } | null>(null);
/** Flow coordinates for placing the new node */
export const pendingFlowPosition = writable<{ x: number; y: number } | null>(null);
export const nodePickerOpen = writable(false);
export const pendingConnection = writable<PendingConnection | null>(null);
/** When inserting from edge "+", the edge to split */
export const pendingSplitEdgeId = writable<string | null>(null);

export function openNodePicker(
	screenPos: { x: number; y: number },
	flowPos: { x: number; y: number },
	pending: PendingConnection | null = null,
	splitEdgeId: string | null = null
) {
	nodePickerScreenPos.set(screenPos);
	pendingFlowPosition.set(flowPos);
	pendingConnection.set(pending);
	pendingSplitEdgeId.set(splitEdgeId);
	nodePickerOpen.set(true);
}

export function closeNodePicker() {
	nodePickerOpen.set(false);
	nodePickerScreenPos.set(null);
	pendingFlowPosition.set(null);
	pendingConnection.set(null);
	pendingSplitEdgeId.set(null);
}

/** Block settings modal (Input / Parameters / Output) — opened by double-click or context menu, not on single select. */
export const nodeInspectorModalId = writable<string | null>(null);

export function openNodeInspector(nodeId: string) {
	nodeInspectorModalId.set(nodeId);
}

export function closeNodeInspector() {
	nodeInspectorModalId.set(null);
}
