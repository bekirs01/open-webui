<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { openNodeInspector } from './editorUiStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;
	export let selected = false;

	type Data = {
		title: string;
		width: number;
		height: number;
		disabled?: boolean;
	};

	export let data: Data;

	$: isDisabled = Boolean(data.disabled);
</script>

<!--
  Размер задаётся на Node (style в store / jsonToFlowNode).
-->
<div
	aria-label="Group {id}"
	role="group"
	on:dblclick|stopPropagation={() => openNodeInspector(id)}
	class="group-node-frame flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border-2 border-dashed box-border bg-gray-50/50 transition-shadow dark:bg-gray-900/40 {isDisabled
		? 'opacity-50 border-gray-300 dark:border-gray-700'
		: selected
			? 'border-emerald-500/90 ring-2 ring-emerald-500/40'
			: 'border-gray-300 dark:border-gray-600'}"
>
	<div
		class="px-2 py-1.5 border-b border-dashed border-gray-200 dark:border-gray-700 flex items-center gap-2 min-h-0"
	>
		<span class="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400 shrink-0">
			{$i18n.t('Group')}
		</span>
		<span class="text-[10px] text-gray-700 dark:text-gray-200 truncate flex-1" title={data.title}>
			{data.title || '—'}
		</span>
	</div>
</div>
