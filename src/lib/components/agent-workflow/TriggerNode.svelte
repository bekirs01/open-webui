<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { setStartNode, startNodeId, updateNodeData } from './workflowStore';
	import { runStepHighlightId } from './editorUiStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;
	export let selected = false;

	type Data = {
		label: string;
		disabled?: boolean;
	};

	export let data: Data;

	$: isStart = id === $startNodeId;
	$: runStep = $runStepHighlightId === id;
	$: isDisabled = Boolean(data.disabled);
</script>

<div
	class="rounded-xl border shadow-md w-[260px] max-w-[90vw] bg-amber-50/80 dark:bg-amber-950/40 transition-shadow {isDisabled
		? 'opacity-60 saturate-50'
		: ''} {runStep
		? 'ring-2 ring-cyan-400 border-cyan-500/80'
		: selected
			? 'ring-2 ring-emerald-500 border-emerald-400'
			: 'border-amber-200 dark:border-amber-900'}"
>
	<div
		class="flex items-center justify-between gap-2 px-3 py-2 border-b border-amber-100 dark:border-amber-900"
	>
		<span class="text-xs font-semibold text-amber-900 dark:text-amber-100 truncate">
			{$i18n.t('Trigger')}
		</span>
		<button
			type="button"
			class="text-[10px] px-2 py-0.5 rounded-md border {isStart
				? 'border-emerald-500 text-emerald-600 dark:text-emerald-400'
				: 'border-gray-300 dark:border-gray-600 text-gray-500'}"
			on:click={() => setStartNode(id)}
		>
			{isStart ? $i18n.t('Start') : $i18n.t('Set as start')}
		</button>
	</div>
	<div class="p-3 space-y-2">
		<p class="text-[11px] text-amber-900/80 dark:text-amber-200/90">
			{$i18n.t('Passes the initial user message into the workflow.')}
		</p>
		<label class="block">
			<span class="text-[10px] uppercase tracking-wide text-amber-800/80 dark:text-amber-300/80"
				>{$i18n.t('Label (optional)')}</span
			>
			<input
				class="mt-1 w-full text-sm rounded-lg border border-amber-200 dark:border-amber-800 px-2 py-1.5 bg-white dark:bg-gray-900"
				value={data.label}
				on:input={(e) =>
					updateNodeData(id, { label: (e.currentTarget as HTMLInputElement).value })}
			/>
		</label>
	</div>
	<Handle
		type="source"
		position={Position.Right}
		class="!w-2.5 !h-2.5 !bg-amber-600 !bg-amber-500 !border-0"
	/>
</div>
