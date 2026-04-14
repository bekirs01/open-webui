<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { updateNodeData } from '../workflowStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;

	type Data = { label: string; disabled?: boolean };
	export let data: Data;
</script>

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
		on:input={(e) => updateNodeData(id, { label: (e.currentTarget as HTMLInputElement).value })}
	/>
</label>
