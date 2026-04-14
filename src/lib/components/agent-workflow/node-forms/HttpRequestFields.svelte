<script lang="ts">
	import { getContext, tick } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import ExpressionInsertBar from '../ExpressionInsertBar.svelte';
	import { insertAtCaret } from '../expressionUi';
	import { updateNodeData } from '../workflowStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;

	type Data = {
		method?: string;
		url?: string;
		headersJson?: string;
		body?: string;
		timeoutSeconds?: number;
		followRedirects?: boolean;
		disabled?: boolean;
	};
	export let data: Data;

	type InsertTarget = 'url' | 'headers' | 'body';
	let insertTarget: InsertTarget = 'url';
	let urlEl: HTMLInputElement | undefined;
	let headersEl: HTMLTextAreaElement | undefined;
	let bodyEl: HTMLTextAreaElement | undefined;

	$: methodVal = (data.method || 'GET').toUpperCase();
	$: urlVal = data.url ?? '';
	$: headersVal = data.headersJson ?? '{}';
	$: bodyVal = data.body ?? '';
	$: followVal = Boolean(data.followRedirects);

	const METHODS = ['GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE'] as const;

	async function insertIntoHttp(snippet: string) {
		if (insertTarget === 'url') {
			const el = urlEl;
			const cur = data.url ?? '';
			const { next, caret } = insertAtCaret(cur, el?.selectionStart, el?.selectionEnd, snippet);
			updateNodeData(id, { url: next });
			await tick();
			if (el) {
				el.focus();
				el.setSelectionRange(caret, caret);
			}
			return;
		}
		if (insertTarget === 'headers') {
			const el = headersEl;
			const cur = data.headersJson ?? '{}';
			const { next, caret } = insertAtCaret(cur, el?.selectionStart, el?.selectionEnd, snippet);
			updateNodeData(id, { headersJson: next });
			await tick();
			if (el) {
				el.focus();
				el.setSelectionRange(caret, caret);
			}
			return;
		}
		const el = bodyEl;
		const cur = data.body ?? '';
		const { next, caret } = insertAtCaret(cur, el?.selectionStart, el?.selectionEnd, snippet);
		updateNodeData(id, { body: next });
		await tick();
		if (el) {
			el.focus();
			el.setSelectionRange(caret, caret);
		}
	}
</script>

<p class="text-[11px] text-teal-900/80 dark:text-teal-200/90">
	{$i18n.t(
		'Calls a public HTTP(S) URL from the server. Use {{input}}, {{json}}, {{user_input}}, {{$json.field}} in URL, headers, or body. Secrets must not be stored in the workflow JSON — use env / future connectors.'
	)}
</p>
<div class="flex flex-wrap items-center gap-2">
	<span class="text-[10px] uppercase text-teal-800/80">{$i18n.t('Insert into')}</span>
	<select
		class="text-[11px] rounded-lg border border-teal-200 dark:border-teal-800 px-2 py-1 bg-white dark:bg-gray-900"
		bind:value={insertTarget}
	>
		<option value="url">{$i18n.t('Request URL')}</option>
		<option value="headers">{$i18n.t('Headers (JSON object)')}</option>
		<option value="body">{$i18n.t('Body (optional)')}</option>
	</select>
</div>
<ExpressionInsertBar flavor="template" onInsert={insertIntoHttp} />
<label class="block">
	<span class="text-[10px] uppercase tracking-wide text-teal-800/80">{$i18n.t('HTTP method')}</span>
	<select
		class="mt-1 w-full text-sm rounded-lg border border-teal-200 dark:border-teal-800 px-2 py-1.5 bg-white dark:bg-gray-900"
		value={methodVal}
		on:change={(e) => updateNodeData(id, { method: (e.currentTarget as HTMLSelectElement).value })}
	>
		{#each METHODS as m (m)}
			<option value={m}>{m}</option>
		{/each}
	</select>
</label>
<label class="block">
	<span class="text-[10px] uppercase tracking-wide text-teal-800/80">{$i18n.t('Request URL')}</span>
	<input
		bind:this={urlEl}
		type="text"
		class="mt-1 w-full text-sm font-mono rounded-lg border border-teal-200 dark:border-teal-800 px-2 py-1.5 bg-white dark:bg-gray-900"
		placeholder="https://api.example.com/v1"
		value={urlVal}
		on:input={(e) => updateNodeData(id, { url: (e.currentTarget as HTMLInputElement).value })}
	/>
</label>
<label class="block">
	<span class="text-[10px] uppercase tracking-wide text-teal-800/80">{$i18n.t('Headers (JSON object)')}</span>
	<textarea
		bind:this={headersEl}
		class="mt-1 w-full text-xs font-mono rounded-lg border border-teal-200 dark:border-teal-800 px-2 py-1.5 min-h-[52px] bg-white dark:bg-gray-900"
		placeholder={'{}'}
		value={headersVal}
		on:input={(e) =>
			updateNodeData(id, { headersJson: (e.currentTarget as HTMLTextAreaElement).value })}
	></textarea>
</label>
<label class="block">
	<span class="text-[10px] uppercase tracking-wide text-teal-800/80">{$i18n.t('Body (optional)')}</span>
	<textarea
		bind:this={bodyEl}
		class="mt-1 w-full text-xs font-mono rounded-lg border border-teal-200 dark:border-teal-800 px-2 py-1.5 min-h-[56px] bg-white dark:bg-gray-900"
		value={bodyVal}
		on:input={(e) => updateNodeData(id, { body: (e.currentTarget as HTMLTextAreaElement).value })}
	></textarea>
</label>
<div class="flex gap-2 items-end">
	<label class="block flex-1">
		<span class="text-[10px] uppercase tracking-wide text-teal-800/80">{$i18n.t('Timeout (seconds)')}</span>
		<input
			type="number"
			min="1"
			max="120"
			class="mt-1 w-full text-sm rounded-lg border border-teal-200 dark:border-teal-800 px-2 py-1.5 bg-white dark:bg-gray-900"
			value={data.timeoutSeconds}
			on:input={(e) => {
				const v = parseInt((e.currentTarget as HTMLInputElement).value, 10);
				updateNodeData(id, {
					timeoutSeconds: Number.isFinite(v) ? Math.min(120, Math.max(1, v)) : 30
				});
			}}
		/>
	</label>
	<label class="flex items-center gap-2 text-[11px] text-teal-900 dark:text-teal-100 pb-1">
		<input
			type="checkbox"
			checked={followVal}
			on:change={(e) =>
				updateNodeData(id, { followRedirects: (e.currentTarget as HTMLInputElement).checked })}
		/>
		{$i18n.t('Follow redirects')}
	</label>
</div>
