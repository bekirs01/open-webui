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
		separator: string;
		disabled?: boolean;
	};

	export let data: Data;

	$: isStart = id === $startNodeId;
	$: runStep = $runStepHighlightId === id;
	$: isDisabled = Boolean(data.disabled);
</script>

<div
	class="rounded-xl border shadow-md w-[280px] max-w-[90vw] bg-violet-50/80 dark:bg-violet-950/40 transition-shadow {isDisabled
		? 'opacity-60 saturate-50'
		: ''} {runStep
		? 'ring-2 ring-cyan-400 border-cyan-500/80'
		: selected
			? 'ring-2 ring-emerald-500 border-emerald-400'
			: 'border-violet-200 dark:border-violet-900'}"
>
	<div
		class="flex items-center justify-between gap-2 px-3 py-2 border-b border-violet-100 dark:border-violet-900"
	>
		<span class="text-xs font-semibold text-violet-900 dark:text-violet-100 truncate">
			{$i18n.t('Merge')}
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
		<p class="text-[11px] text-violet-900/80 dark:text-violet-200/90">
			{$i18n.t('Waits for all incoming branches, then joins their outputs.')}
		</p>
		<label class="block">
			<span class="text-[10px] uppercase tracking-wide text-violet-800/80">{$i18n.t('Separator')}</span>
			<textarea
				class="mt-1 w-full text-sm rounded-lg border border-violet-200 dark:border-violet-800 px-2 py-1.5 min-h-[56px] font-mono bg-white dark:bg-gray-900"
				placeholder="---"
				value={data.separator}
				on:input={(e) =>
					updateNodeData(id, { separator: (e.currentTarget as HTMLTextAreaElement).value })}
			></textarea>
		</label>
	</div>
	<Handle
		type="target"
		position={Position.Left}
		class="!w-2.5 !h-2.5 !bg-violet-500 !border-0"
	/>
	<Handle
		type="source"
		position={Position.Right}
		class="!w-2.5 !h-2.5 !bg-violet-600 !border-0"
	/>
</div>
