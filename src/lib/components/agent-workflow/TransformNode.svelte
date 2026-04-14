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
		template: string;
		disabled?: boolean;
	};

	export let data: Data;

	const entry = NODE_REGISTRY.transform;

	$: isStart = id === $startNodeId;
	$: runActive = $runActiveNodeId === id;
	$: runPath = $runPathNodeIds.has(id);
	$: isDisabled = Boolean(data.disabled);
	$: preview = (data.template ?? '').replace(/\s+/g, ' ').trim().slice(0, 42);
</script>

<div
	role="group"
	on:dblclick|stopPropagation={() => openNodeInspector(id)}
	class="relative rounded-lg border shadow-sm w-[196px] max-w-[90vw] bg-sky-50/90 dark:bg-sky-950/50 transition-shadow {isDisabled
		? 'opacity-60 saturate-50'
		: ''} {runActive
		? 'ring-2 ring-cyan-400 border-cyan-500/80 animate-pulse'
		: runPath
			? 'ring-2 ring-amber-500/90 border-amber-600/70'
			: selected
				? 'ring-2 ring-emerald-500 border-emerald-400'
				: 'border-sky-200 dark:border-sky-900'}"
>
	{#if runActive}
		<div
			class="absolute right-1.5 top-1.5 h-3.5 w-3.5 rounded-full border-2 border-cyan-300 border-t-transparent animate-spin dark:border-cyan-500 dark:border-t-transparent"
			aria-hidden="true"
		/>
	{/if}
	<div class="flex items-center gap-1.5 px-2 py-1.5 border-b border-sky-100 dark:border-sky-900">
		<span class="text-sm leading-none" aria-hidden="true">{entry.icon}</span>
		<span class="text-[11px] font-semibold text-sky-900 dark:text-sky-100 flex-1 truncate">
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
	<div class="px-2 py-1 text-[9px] font-mono text-sky-900/80 dark:text-sky-200/80 truncate" title={data.template}>
		{preview || '…'}
	</div>
	<Handle
		type="target"
		position={Position.Left}
		class="!w-2.5 !h-2.5 !bg-sky-500 !border-0"
	/>
	<Handle
		type="source"
		position={Position.Right}
		class="!w-2.5 !h-2.5 !bg-sky-600 !border-0"
	/>
</div>
