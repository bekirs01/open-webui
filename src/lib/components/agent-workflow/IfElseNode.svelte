<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { NODE_REGISTRY } from './nodeRegistry';
	import { openNodeInspector, runActiveNodeId, runPathNodeIds } from './editorUiStore';
	import { setStartNode, startNodeId } from './workflowStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;
	export let selected = false;

	type Data = {
		condition: string;
		conditionMode: 'substring' | 'json' | 'expression';
		conditionExpression?: string;
		jsonPath: string;
		jsonOperator: string;
		compareValue: string;
		disabled?: boolean;
	};

	export let data: Data;

	const entry = NODE_REGISTRY.ifElse;

	$: isStart = id === $startNodeId;
	$: runActive = $runActiveNodeId === id;
	$: runPath = $runPathNodeIds.has(id);
	$: isDisabled = Boolean(data.disabled);
	$: mode = data.conditionMode ?? 'substring';
	$: modeLabel =
		mode === 'json'
			? $i18n.t('JSON path')
			: mode === 'expression'
				? $i18n.t('Expression')
				: $i18n.t('Substring');
</script>

<div
	role="group"
	on:dblclick|stopPropagation={() => openNodeInspector(id)}
	class="relative rounded-lg border shadow-sm w-[196px] max-w-[92vw] bg-violet-50/90 dark:bg-violet-950/50 transition-shadow {isDisabled
		? 'opacity-60 saturate-50'
		: ''} {runActive
		? 'ring-2 ring-cyan-400 border-cyan-500/80 animate-pulse'
		: runPath
			? 'ring-2 ring-amber-500/90 border-amber-600/70'
			: selected
				? 'ring-2 ring-emerald-500 border-emerald-400'
				: 'border-violet-200 dark:border-violet-900'}"
>
	{#if runActive}
		<div
			class="absolute right-1.5 top-1.5 h-3.5 w-3.5 rounded-full border-2 border-cyan-300 border-t-transparent animate-spin dark:border-cyan-500 dark:border-t-transparent"
			aria-hidden="true"
		/>
	{/if}
	<div
		class="flex items-center gap-1.5 px-2 py-1.5 border-b border-violet-100 dark:border-violet-900"
	>
		<span class="text-sm leading-none" aria-hidden="true">{entry.icon}</span>
		<span class="text-[11px] font-semibold text-violet-900 dark:text-violet-100 flex-1 truncate">
			{$i18n.t(entry.labelKey)}
		</span>
		<button
			type="button"
			class="text-[9px] px-1.5 py-0.5 rounded border shrink-0 {isStart
				? 'border-emerald-500 text-emerald-600 dark:text-emerald-400'
				: 'border-gray-300 dark:border-gray-600 text-gray-500'}"
			on:click={() => setStartNode(id)}
		>
			{isStart ? $i18n.t('Start') : '○'}
		</button>
	</div>
	<div class="px-2 py-1 text-[9px] text-violet-800/90 dark:text-violet-200/90 flex justify-between gap-1">
		<span class="truncate">{modeLabel}</span>
		<span class="text-violet-600/80 dark:text-violet-400/80 shrink-0">T / F</span>
	</div>
	<Handle
		type="target"
		position={Position.Left}
		class="!w-2.5 !h-2.5 !bg-violet-500 !border-0"
	/>
	<Handle
		id="true"
		type="source"
		position={Position.Right}
		class="!w-2.5 !h-2.5 !bg-emerald-500 !border-0"
		style="top: 38%"
	/>
	<Handle
		id="false"
		type="source"
		position={Position.Right}
		class="!w-2.5 !h-2.5 !bg-rose-500 !border-0"
		style="top: 62%"
	/>
</div>
