<script lang="ts">
	import { getContext, tick } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import ExpressionInsertBar from '../ExpressionInsertBar.svelte';
	import { insertAtCaret } from '../expressionUi';
	import { updateNodeData } from '../workflowStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;

	type Data = { template: string; disabled?: boolean };
	export let data: Data;

	let templateEl: HTMLTextAreaElement | undefined;

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
