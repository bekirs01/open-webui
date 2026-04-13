<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';
	import { get } from 'svelte/store';

	import {
		closeNodePicker,
		nodePickerOpen,
		nodePickerScreenPos,
		pendingFlowPosition,
		pendingConnection,
		pendingSplitEdgeId
	} from './editorUiStore';
	import { addNodeAt, splitEdgeWithNewNode } from './workflowStore';
	import { pushUndoSnapshot } from './workflowHistory';
	import { NODE_REGISTRY, FLOW_NODE_TYPES, type FlowNodeTypeId } from './nodeRegistry';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let defaultModelId: string;
	export let onPicked: () => void;

	function pick(type: FlowNodeTypeId) {
		const flowPos = get(pendingFlowPosition) ?? { x: 120, y: 120 };
		const conn = get(pendingConnection);
		const splitId = get(pendingSplitEdgeId);

		pushUndoSnapshot();
		if (splitId) {
			splitEdgeWithNewNode(splitId, type, flowPos, defaultModelId);
		} else {
			addNodeAt(type, flowPos, defaultModelId, {
				connectFrom: conn
					? { source: conn.source, sourceHandle: conn.sourceHandle ?? undefined }
					: undefined
			});
		}
		closeNodePicker();
		onPicked();
	}

	function onBackdrop(ev: MouseEvent) {
		if (ev.target === ev.currentTarget) closeNodePicker();
	}
</script>

{#if $nodePickerOpen && $nodePickerScreenPos}
	<!-- svelte-ignore a11y-click-events-have-key-events -->
	<!-- svelte-ignore a11y-no-static-element-interactions -->
	<div
		class="fixed inset-0 z-[100] bg-black/20"
		role="presentation"
		on:click={onBackdrop}
	>
		<div
			class="absolute z-[101] min-w-[220px] max-w-[90vw] rounded-xl border border-gray-200 bg-white p-2 shadow-xl dark:border-gray-700 dark:bg-gray-900"
			style="left: {Math.min($nodePickerScreenPos.x, typeof window !== 'undefined' ? window.innerWidth - 240 : 0)}px; top: {Math.min($nodePickerScreenPos.y, typeof window !== 'undefined' ? window.innerHeight - 280 : 0)}px;"
			on:click|stopPropagation
		>
			<div class="px-2 pb-2 text-xs font-medium text-gray-500 dark:text-gray-400">
				{$i18n.t('Add block')}
			</div>
			<div class="flex flex-col gap-1">
				{#each FLOW_NODE_TYPES as ft (ft)}
					<button
						type="button"
						class="rounded-lg px-3 py-2 text-left text-sm hover:bg-gray-100 dark:hover:bg-gray-800 flex items-center gap-2"
						on:click={() => pick(ft)}
					>
						{#if NODE_REGISTRY[ft].icon}
							<span class="shrink-0 w-5 text-center" aria-hidden="true"
								>{NODE_REGISTRY[ft].icon}</span
							>
						{/if}
						<span>{$i18n.t(NODE_REGISTRY[ft].labelKey)}</span>
					</button>
				{/each}
			</div>
		</div>
	</div>
{/if}
