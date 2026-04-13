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

	type ConditionMode = 'substring' | 'json' | 'expression';

	type Data = {
		condition: string;
		conditionMode: ConditionMode;
		conditionExpression?: string;
		jsonPath: string;
		jsonOperator: string;
		compareValue: string;
		disabled?: boolean;
	};

	export let data: Data;

	let conditionEl: HTMLTextAreaElement | undefined;
	let exprEl: HTMLTextAreaElement | undefined;

	const JSON_OPS = [
		'equals',
		'notequals',
		'contains',
		'notcontains',
		'exists',
		'notexists',
		'isempty',
		'isnotempty',
		'gt',
		'gte',
		'lt',
		'lte'
	] as const;

	$: isStart = id === $startNodeId;
	$: runStep = $runStepHighlightId === id;
	$: isDisabled = Boolean(data.disabled);
	$: mode = data.conditionMode ?? 'substring';

	async function insertIntoSubstring(snippet: string) {
		const el = conditionEl;
		const cur = data.condition ?? '';
		const { next, caret } = insertAtCaret(cur, el?.selectionStart, el?.selectionEnd, snippet);
		updateNodeData(id, { condition: next });
		await tick();
		if (el) {
			el.focus();
			el.setSelectionRange(caret, caret);
		}
	}

	async function insertIntoExpression(snippet: string) {
		const el = exprEl;
		const cur = data.conditionExpression ?? '';
		const { next, caret } = insertAtCaret(cur, el?.selectionStart, el?.selectionEnd, snippet);
		updateNodeData(id, { conditionExpression: next, conditionMode: 'expression' });
		await tick();
		if (el) {
			el.focus();
			el.setSelectionRange(caret, caret);
		}
	}
</script>

<div
	class="rounded-xl border shadow-md w-[300px] max-w-[92vw] bg-violet-50/80 dark:bg-violet-950/40 transition-shadow {isDisabled
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
			IF / ELSE
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
			{$i18n.t(
				'Previous step sends JSON (n8n-style: items[0].json). Choose text substring match, JSON path compare, or a formula like ={{$json.age > 18}} (evaluated per item).'
			)}
		</p>
		<label class="block">
			<span class="text-[10px] uppercase tracking-wide text-violet-800/80">{$i18n.t('Mode')}</span>
			<select
				class="mt-1 w-full text-sm rounded-lg border border-violet-200 dark:border-violet-800 px-2 py-1.5 bg-white dark:bg-gray-900"
				value={mode}
				on:change={(e) =>
					updateNodeData(id, {
						conditionMode: (e.currentTarget as HTMLSelectElement).value as ConditionMode
					})}
			>
				<option value="substring">{$i18n.t('Text contains (substring)')}</option>
				<option value="json">{$i18n.t('JSON path compare')}</option>
				<option value="expression">{$i18n.t('Expression (formula)')}</option>
			</select>
		</label>

		{#if mode === 'substring'}
			<p class="text-[10px] text-amber-800/90 dark:text-amber-200/90">
				{$i18n.t(
					'Substring mode checks if this phrase appears anywhere in the previous step text — it is not numeric equality. For value equals 1 use JSON path compare.'
				)}
			</p>
			<ExpressionInsertBar flavor="template" onInsert={insertIntoSubstring} />
			<label class="block">
				<span class="text-[10px] uppercase tracking-wide text-violet-800/80">{$i18n.t('Condition')}</span
				>
				<textarea
					bind:this={conditionEl}
					class="mt-1 w-full text-sm rounded-lg border border-violet-200 dark:border-violet-800 px-2 py-1.5 min-h-[56px] bg-white dark:bg-gray-900"
					placeholder={$i18n.t('Substring must appear in previous step text (case-insensitive)')}
					value={data.condition}
					on:input={(e) =>
						updateNodeData(id, { condition: (e.currentTarget as HTMLTextAreaElement).value })}
				></textarea>
			</label>
		{:else if mode === 'expression'}
			<p class="text-[10px] text-violet-800/90 dark:text-violet-200/90">
				{$i18n.t(
					'Use a formula that evaluates to true/false. Prefix with = for expressions, e.g. ={{$json.ok == true}} or ={{$json.age > 18}}. If set, this overrides substring / JSON path modes on the server.'
				)}
			</p>
			<ExpressionInsertBar flavor="condition" onInsert={insertIntoExpression} />
			<label class="block">
				<span class="text-[10px] uppercase tracking-wide text-violet-800/80"
					>{$i18n.t('Condition expression')}</span
				>
				<textarea
					bind:this={exprEl}
					class="mt-1 w-full text-xs font-mono rounded-lg border border-violet-200 dark:border-violet-800 px-2 py-1.5 min-h-[72px] bg-white dark:bg-gray-900"
					placeholder={'=' + '{{$json.age > 18}}'}
					value={data.conditionExpression ?? ''}
					on:input={(e) =>
						updateNodeData(id, {
							conditionExpression: (e.currentTarget as HTMLTextAreaElement).value,
							conditionMode: 'expression'
						})}
				></textarea>
			</label>
		{:else}
			<label class="block">
				<span class="text-[10px] uppercase tracking-wide text-violet-800/80">{$i18n.t('JSON path')}</span
				>
				<input
					type="text"
					class="mt-1 w-full text-sm font-mono rounded-lg border border-violet-200 dark:border-violet-800 px-2 py-1.5 bg-white dark:bg-gray-900"
					placeholder="items.0.json.userInput"
					value={data.jsonPath}
					on:input={(e) =>
						updateNodeData(id, { jsonPath: (e.currentTarget as HTMLInputElement).value })}
				/>
			</label>
			<label class="block">
				<span class="text-[10px] uppercase tracking-wide text-violet-800/80">{$i18n.t('Operator')}</span
				>
				<select
					class="mt-1 w-full text-sm rounded-lg border border-violet-200 dark:border-violet-800 px-2 py-1.5 bg-white dark:bg-gray-900"
					value={data.jsonOperator}
					on:change={(e) =>
						updateNodeData(id, { jsonOperator: (e.currentTarget as HTMLSelectElement).value })}
				>
					{#each JSON_OPS as op (op)}
						<option value={op}>{op}</option>
					{/each}
				</select>
			</label>
			<label class="block">
				<span class="text-[10px] uppercase tracking-wide text-violet-800/80"
					>{$i18n.t('Compare value')}</span
				>
				<input
					type="text"
					class="mt-1 w-full text-sm rounded-lg border border-violet-200 dark:border-violet-800 px-2 py-1.5 bg-white dark:bg-gray-900"
					placeholder={$i18n.t('Ignored for exists / empty checks')}
					value={data.compareValue}
					on:input={(e) =>
						updateNodeData(id, { compareValue: (e.currentTarget as HTMLInputElement).value })}
				/>
			</label>
		{/if}
		<div class="flex justify-end gap-6 text-[10px] text-violet-700 dark:text-violet-300 pr-1">
			<span>true →</span>
			<span>false →</span>
		</div>
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
		style="top: 35%"
	/>
	<Handle
		id="false"
		type="source"
		position={Position.Right}
		class="!w-2.5 !h-2.5 !bg-rose-500 !border-0"
		style="top: 65%"
	/>
</div>
