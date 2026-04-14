<script lang="ts">
	import { BaseEdge, EdgeLabelRenderer } from '@xyflow/svelte';
	import { getSmoothStepPath, type SmoothStepPathOptions } from '@xyflow/system';
	import { getContext } from 'svelte';

	import { runPathEdgeIds } from './editorUiStore';

	export let id: string;
	export let sourceX: number;
	export let sourceY: number;
	export let targetX: number;
	export let targetY: number;
	export let sourcePosition: import('@xyflow/system').Position;
	export let targetPosition: import('@xyflow/system').Position;
	export let markerStart: string | undefined = undefined;
	export let markerEnd: string | undefined = undefined;
	export let style: string | undefined = undefined;
	/** Wider hit-area so connections are easier to select and delete. */
	export let interactionWidth: number | undefined = 28;
	export let pathOptions: SmoothStepPathOptions | undefined = undefined;
	/** Passed by EdgeWrapper — kept for API compatibility */
	export let source = '';
	export let target = '';
	export let label: string | undefined = undefined;
	export let labelStyle: string | undefined = undefined;
	export let data: Record<string, unknown> | undefined = undefined;
	export let animated = false;
	export let selected = false;
	export let selectable = true;
	export let deletable = true;
	export let type = 'workflow';
	export let sourceHandleId: string | null | undefined = undefined;
	export let targetHandleId: string | null | undefined = undefined;

	$: edgeDisabled = Boolean(data?.disabled);
	$: onRunPath = $runPathEdgeIds.has(id);

	const onInsert = getContext<((edgeId: string) => void) | undefined>('workflowEdgeInsert');

	$: [path, labelX, labelY] = getSmoothStepPath({
		sourceX,
		sourceY,
		targetX,
		targetY,
		sourcePosition,
		targetPosition,
		borderRadius: pathOptions?.borderRadius,
		offset: pathOptions?.offset
	});

	function handleInsertClick(e: MouseEvent) {
		e.stopPropagation();
		e.preventDefault();
		onInsert?.(id);
	}
</script>

<BaseEdge
	{id}
	{path}
	labelX={undefined}
	labelY={undefined}
	{markerStart}
	{markerEnd}
	{interactionWidth}
	style={[
		edgeDisabled ? 'opacity:0.35;stroke-dasharray:6 4' : '',
		onRunPath ? 'stroke:#d97706;stroke-width:2.5' : '',
		style ?? ''
	]
		.filter(Boolean)
		.join(';')}
/>

{#if onInsert}
	<EdgeLabelRenderer>
		<div
			class="workflow-edge-insert pointer-events-auto"
			style:transform="translate(-50%, -50%) translate({labelX}px, {labelY}px)"
		>
			<button
				type="button"
				title="Insert node"
				class="flex h-6 w-6 items-center justify-center rounded-full border border-gray-300 bg-white text-sm font-semibold text-gray-700 shadow-sm hover:bg-emerald-50 hover:border-emerald-500 dark:border-gray-600 dark:bg-gray-900 dark:text-gray-100 dark:hover:bg-emerald-950/50"
				on:click={handleInsertClick}
			>
				+
			</button>
		</div>
	</EdgeLabelRenderer>
{/if}

<style>
	.workflow-edge-insert {
		position: absolute;
		z-index: 2;
	}
</style>
