<script lang="ts">
	import { onDestroy, onMount, setContext } from 'svelte';
	import { useSvelteFlow } from '@xyflow/svelte';
	import type { FinalConnectionState } from '@xyflow/system';
	import { isInputDOMNode } from '@xyflow/system';
	import { ControlButton, Controls } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	import { get } from 'svelte/store';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { openNodePicker, workflowContextMenu } from './editorUiStore';
	import { connectEndBridge } from './connectBridge';
	import { addNodeAt, toggleEdgeDisabled, toggleNodeDisabled } from './workflowStore';
	import type { FlowNodeTypeId } from './nodeRegistry';
	import {
		canRedoStore,
		canUndoStore,
		pushUndoSnapshot,
		redoWorkflow,
		undoWorkflow
	} from './workflowHistory';
	import {
		copySubgraphToClipboard,
		duplicateNodesByIds,
		hasClipboard,
		pasteClipboardAt
	} from './workflowClipboard';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	/** Called after structural edits (connect, delete, add) */
	export let onStructureChange: () => void;
	export let defaultModelId: string;

	const { screenToFlowPosition, deleteElements, fitView, getNodes, getEdges } = useSvelteFlow();

	let lastFlowPos = { x: 160, y: 120 };

	function pointerClient(ev: MouseEvent | TouchEvent): { x: number; y: number } {
		if ('touches' in ev && ev.touches.length > 0) {
			return { x: ev.touches[0].clientX, y: ev.touches[0].clientY };
		}
		const m = ev as MouseEvent;
		return { x: m.clientX, y: m.clientY };
	}

	function handleConnectEnd(ev: MouseEvent | TouchEvent, state: FinalConnectionState) {
		if (!state.fromNode) return;
		if (state.toNode) return;
		const fromHandle = state.fromHandle;
		requestAnimationFrame(() => {
			const { x, y } = pointerClient(ev);
			const flowPos = screenToFlowPosition({ x, y });
			openNodePicker(
				{ x, y },
				flowPos,
				{
					source: state.fromNode!.id,
					sourceHandle: fromHandle?.id ?? null
				},
				null
			);
		});
	}

	function handleEdgeInsert(edgeId: string) {
		const cx = window.innerWidth / 2;
		const cy = window.innerHeight / 2;
		const flowPos = screenToFlowPosition({ x: cx, y: cy });
		openNodePicker({ x: cx, y: cy }, flowPos, null, edgeId);
	}

	setContext('workflowEdgeInsert', handleEdgeInsert);

	function canvasModifierClick(ev: MouseEvent) {
		if (!ev.shiftKey) return;
		const t = ev.target as HTMLElement | null;
		if (!t) return;
		if (t.closest?.('.svelte-flow__node')) return;
		if (t.closest?.('.svelte-flow__controls')) return;
		if (t.closest?.('.workflow-edge-insert')) return;
		ev.preventDefault();
		const flowPos = screenToFlowPosition({ x: ev.clientX, y: ev.clientY });
		openNodePicker({ x: ev.clientX, y: ev.clientY }, flowPos, null, null);
	}

	function canvasDblClick(ev: MouseEvent) {
		const t = ev.target as HTMLElement | null;
		if (!t) return;
		if (t.closest?.('.svelte-flow__node')) return;
		if (t.closest?.('.svelte-flow__controls')) return;
		ev.preventDefault();
		const flowPos = screenToFlowPosition({ x: ev.clientX, y: ev.clientY });
		openNodePicker({ x: ev.clientX, y: ev.clientY }, flowPos, null, null);
	}

	function trackFlowPointer(ev: MouseEvent) {
		lastFlowPos = screenToFlowPosition({ x: ev.clientX, y: ev.clientY });
	}

	function onFlowContextMenu(ev: MouseEvent) {
		const t = ev.target as HTMLElement | null;
		if (!t) return;
		const nodeEl = t.closest?.('.svelte-flow__node[data-id]') as HTMLElement | null;
		const edgeEl = t.closest?.('.svelte-flow__edge[data-id]') as HTMLElement | null;
		if (nodeEl?.dataset.id) {
			ev.preventDefault();
			ev.stopPropagation();
			workflowContextMenu.set({
				kind: 'node',
				id: nodeEl.dataset.id,
				x: ev.clientX,
				y: ev.clientY
			});
			return;
		}
		if (edgeEl?.dataset.id) {
			ev.preventDefault();
			ev.stopPropagation();
			workflowContextMenu.set({
				kind: 'edge',
				id: edgeEl.dataset.id,
				x: ev.clientX,
				y: ev.clientY
			});
		}
	}

	function closeContextMenu() {
		workflowContextMenu.set(null);
	}

	async function contextDeleteNode(id: string) {
		const n = getNodes().find((x) => x.id === id);
		if (n) await deleteElements({ nodes: [n], edges: [] });
		closeContextMenu();
		onStructureChange();
	}

	async function contextDeleteEdge(id: string) {
		const e = getEdges().find((x) => x.id === id);
		if (e) await deleteElements({ nodes: [], edges: [e] });
		closeContextMenu();
		onStructureChange();
	}

	function contextDuplicateNode(id: string) {
		duplicateNodesByIds([id]);
		closeContextMenu();
		onStructureChange();
	}

	function contextToggleNodeDisabled(id: string) {
		toggleNodeDisabled(id);
		closeContextMenu();
		onStructureChange();
	}

	function contextToggleEdgeDisabled(id: string) {
		toggleEdgeDisabled(id);
		closeContextMenu();
		onStructureChange();
	}

	function onWindowKeyDown(ev: KeyboardEvent) {
		if (isInputDOMNode(ev)) return;
		const mod = ev.ctrlKey || ev.metaKey;
		if (mod && ev.key.toLowerCase() === 'z' && !ev.shiftKey) {
			ev.preventDefault();
			if (undoWorkflow()) onStructureChange();
			return;
		}
		if (mod && (ev.key.toLowerCase() === 'y' || (ev.key.toLowerCase() === 'z' && ev.shiftKey))) {
			ev.preventDefault();
			if (redoWorkflow()) onStructureChange();
			return;
		}
		if (mod && ev.key.toLowerCase() === 'c') {
			const sel = getNodes().filter((n) => n.selected).map((n) => n.id);
			if (sel.length) {
				ev.preventDefault();
				copySubgraphToClipboard(sel);
			}
			return;
		}
		if (mod && ev.key.toLowerCase() === 'v') {
			if (!hasClipboard()) return;
			ev.preventDefault();
			if (pasteClipboardAt(lastFlowPos)) onStructureChange();
			return;
		}
	}

	function onWindowPointerDown(ev: MouseEvent) {
		if (
			!get(workflowContextMenu) ||
			(ev.target as HTMLElement)?.closest?.('.workflow-ctx-menu')
		) {
			return;
		}
		closeContextMenu();
	}

	let off: (() => void) | undefined;
	onMount(() => {
		connectEndBridge.set(handleConnectEnd);
		const el = document.querySelector('[data-testid="svelte-flow__wrapper"]') as HTMLElement | null;
		if (el) {
			el.addEventListener('click', canvasModifierClick, true);
			el.addEventListener('dblclick', canvasDblClick, true);
			el.addEventListener('mousemove', trackFlowPointer);
			el.addEventListener('contextmenu', onFlowContextMenu);
			off = () => {
				el.removeEventListener('click', canvasModifierClick, true);
				el.removeEventListener('dblclick', canvasDblClick, true);
				el.removeEventListener('mousemove', trackFlowPointer);
				el.removeEventListener('contextmenu', onFlowContextMenu);
			};
		}
		window.addEventListener('keydown', onWindowKeyDown, true);
		window.addEventListener('pointerdown', onWindowPointerDown);
		requestAnimationFrame(() => {
			fitView({ padding: 0.2, duration: 200 });
		});
	});

	onDestroy(() => {
		connectEndBridge.set(null);
		off?.();
		window.removeEventListener('keydown', onWindowKeyDown, true);
		window.removeEventListener('pointerdown', onWindowPointerDown);
	});

	async function fitToScreen() {
		await fitView({ padding: 0.2, duration: 250 });
	}

	async function deleteSelected() {
		const selectedNodes = getNodes().filter((n) => n.selected);
		const selectedEdges = getEdges().filter((e) => e.selected);
		if (selectedNodes.length === 0 && selectedEdges.length === 0) return;
		await deleteElements({ nodes: selectedNodes, edges: selectedEdges });
		onStructureChange();
	}

	/** Toolbar / shortcuts: open node picker at viewport center */
	export function openPickerCenter() {
		const el = document.querySelector(
			'[data-testid="svelte-flow__wrapper"]'
		) as HTMLElement | null;
		const r = el?.getBoundingClientRect();
		const cx = r ? r.left + r.width / 2 : window.innerWidth / 2;
		const cy = r ? r.top + r.height / 2 : window.innerHeight / 2;
		const flowPos = screenToFlowPosition({ x: cx, y: cy });
		openNodePicker({ x: cx, y: cy }, flowPos, null, null);
	}

	export function quickAddAtCenter(flowType: FlowNodeTypeId) {
		const el = document.querySelector(
			'[data-testid="svelte-flow__wrapper"]'
		) as HTMLElement | null;
		const r = el?.getBoundingClientRect();
		const cx = r ? r.left + r.width / 2 : window.innerWidth / 2;
		const cy = r ? r.top + r.height / 2 : window.innerHeight / 2;
		const flowPos = screenToFlowPosition({ x: cx, y: cy });
		pushUndoSnapshot();
		addNodeAt(flowType, flowPos, defaultModelId, {});
		onStructureChange();
	}

	$: ctx = $workflowContextMenu;
	$: undoEnabled = $canUndoStore;
	$: redoEnabled = $canRedoStore;
</script>

<Controls showLock={false} showFitView={false}>
	<ControlButton
		on:click={() => {
			if (undoWorkflow()) onStructureChange();
		}}
		disabled={!undoEnabled}
		title="Undo"
	>
		<span class="text-xs">↶</span>
	</ControlButton>
	<ControlButton
		on:click={() => {
			if (redoWorkflow()) onStructureChange();
		}}
		disabled={!redoEnabled}
		title="Redo"
	>
		<span class="text-xs">↷</span>
	</ControlButton>
	<ControlButton on:click={fitToScreen} title="Fit view">
		<span class="text-xs font-semibold">⊡</span>
	</ControlButton>
	<ControlButton
		on:click={deleteSelected}
		title={$i18n.t('Delete selected nodes or connections')}
	>
		<span class="text-xs">⌫</span>
	</ControlButton>
</Controls>

{#if ctx}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="workflow-ctx-menu fixed z-[120] min-w-[180px] rounded-lg border border-gray-200 bg-white py-1 text-sm shadow-xl dark:border-gray-700 dark:bg-gray-900"
		style="left: {Math.min(ctx.x, typeof window !== 'undefined' ? window.innerWidth - 200 : ctx.x)}px; top: {Math.min(ctx.y, typeof window !== 'undefined' ? window.innerHeight - 200 : ctx.y)}px;"
		role="menu"
		on:click|stopPropagation
	>
		{#if ctx.kind === 'node'}
			<button
				type="button"
				class="w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-800"
				on:click={() => contextDuplicateNode(ctx.id)}
			>
				{$i18n.t('Duplicate')}
			</button>
			<button
				type="button"
				class="w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-800"
				on:click={() => contextToggleNodeDisabled(ctx.id)}
			>
				{$i18n.t('Toggle disabled')}
			</button>
			<button
				type="button"
				class="w-full px-3 py-2 text-left text-red-600 hover:bg-gray-100 dark:hover:bg-gray-800"
				on:click={() => contextDeleteNode(ctx.id)}
			>
				{$i18n.t('Delete')}
			</button>
		{:else}
			<button
				type="button"
				class="w-full px-3 py-2 text-left hover:bg-gray-100 dark:hover:bg-gray-800"
				on:click={() => contextToggleEdgeDisabled(ctx.id)}
			>
				{$i18n.t('Toggle disabled')}
			</button>
			<button
				type="button"
				class="w-full px-3 py-2 text-left text-red-600 hover:bg-gray-100 dark:hover:bg-gray-800"
				on:click={() => contextDeleteEdge(ctx.id)}
			>
				{$i18n.t('Delete')}
			</button>
		{/if}
	</div>
{/if}
