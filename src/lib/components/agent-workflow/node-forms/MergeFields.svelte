<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { updateNodeData } from '../workflowStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;

	type Data = { separator: string; disabled?: boolean };
	export let data: Data;
</script>

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
