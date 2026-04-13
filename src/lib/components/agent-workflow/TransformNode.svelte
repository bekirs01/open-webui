<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext, tick } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import ExpressionInsertBar from './ExpressionInsertBar.svelte';
	import { insertAtCaret } from './expressionUi';
	import { setStartNode, startNodeId, updateNodeData } from './workflowStore';
	import { runStepHighlightId } from './editorUiStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;
	export let selected = false;

	type Data = {
		template: string;
		disabled?: boolean;
	};

	export let data: Data;

	let templateEl: HTMLTextAreaElement | undefined;

	$: isStart = id === $startNodeId;
	$: runStep = $runStepHighlightId === id;
	$: isDisabled = Boolean(data.disabled);

	async function insertTemplate(snippet: string) {
		const el = templateEl;
		const cur = data.template ?? '';
		const { next, caret } = insertAtCaret(cur, el?.selectionStart, el?.selectionEnd, snippet);
		updateNodeData(id, { template: next });
		await tick();
		if (el) {
			el.focus();
			el.setSelectionRange(caret, caret);
		}
	}
</script>

<div
	class="rounded-xl border shadow-md w-[280px] max-w-[90vw] bg-sky-50/80 dark:bg-sky-950/40 transition-shadow {isDisabled
		? 'opacity-60 saturate-50'
		: ''} {runStep
		? 'ring-2 ring-cyan-400 border-cyan-500/80'
		: selected
			? 'ring-2 ring-emerald-500 border-emerald-400'
			: 'border-sky-200 dark:border-sky-900'}"
>
	<div
		class="flex items-center justify-between gap-2 px-3 py-2 border-b border-sky-100 dark:border-sky-900"
	>
		<span class="text-xs font-semibold text-sky-900 dark:text-sky-100 truncate">
			{$i18n.t('Transform')}
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
		<p class="text-[11px] text-sky-900/80 dark:text-sky-200/90">
			{$i18n.t(
				'{{input}} = short text from previous step; {{json}} = JSON of items[0].json; {{$json.field}} is substituted per item (same as HTTP / IF expressions).'
			)}
		</p>
		<ExpressionInsertBar flavor="template" onInsert={insertTemplate} />
		<label class="block">
			<span class="text-[10px] uppercase tracking-wide text-sky-800/80">{$i18n.t('Template')}</span>
			<textarea
				bind:this={templateEl}
				class="mt-1 w-full text-sm rounded-lg border border-sky-200 dark:border-sky-800 px-2 py-1.5 min-h-[80px] font-mono bg-white dark:bg-gray-900"
				placeholder={'{{input}}'}
				value={data.template}
				on:input={(e) =>
					updateNodeData(id, { template: (e.currentTarget as HTMLTextAreaElement).value })}
			></textarea>
		</label>
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
