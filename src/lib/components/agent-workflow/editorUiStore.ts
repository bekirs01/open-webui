import { writable } from 'svelte/store';

/** Canvas highlight during run replay (node id). */
export const runStepHighlightId = writable<string | null>(null);

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
