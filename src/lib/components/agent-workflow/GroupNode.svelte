<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { updateNodeData } from './workflowStore';

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
  Размер задаётся только на Node (style в store / jsonToFlowNode).
  Внутренний корень — ровно 100% родителя, без второго width/height (иначе «двойная» рамка и сдвиг).
-->
<div
	class="group-node-frame flex h-full w-full min-h-0 min-w-0 flex-col overflow-hidden rounded-xl border-2 border-dashed box-border bg-gray-50/50 transition-shadow dark:bg-gray-900/40 {isDisabled
		? 'opacity-50 border-gray-300 dark:border-gray-700'
		: selected
			? 'border-emerald-500/90 ring-2 ring-emerald-500/40'
			: 'border-gray-300 dark:border-gray-600'}"
>
	<div class="px-2 py-1.5 border-b border-dashed border-gray-200 dark:border-gray-700">
		<span class="text-[10px] font-semibold uppercase tracking-wide text-gray-500 dark:text-gray-400">
			{$i18n.t('Group')}
		</span>
	</div>
	<div class="p-2 space-y-2">
		<label class="block">
			<span class="text-[10px] text-gray-500 dark:text-gray-400">{$i18n.t('Title')}</span>
			<input
				type="text"
				class="mt-0.5 w-full text-xs rounded-md border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-950 px-2 py-1"
				value={data.title}
				on:input={(e) => updateNodeData(id, { title: (e.currentTarget as HTMLInputElement).value })}
			/>
		</label>
		<div class="flex gap-2">
			<label class="flex-1">
				<span class="text-[10px] text-gray-500">W</span>
				<input
					type="number"
					min="120"
					class="mt-0.5 w-full text-xs rounded-md border border-gray-200 dark:border-gray-700 px-1 py-0.5 bg-white dark:bg-gray-950"
					value={data.width}
					on:input={(e) =>
						updateNodeData(id, {
							width: Math.max(120, Number((e.currentTarget as HTMLInputElement).value) || 320)
						})}
				/>
			</label>
			<label class="flex-1">
				<span class="text-[10px] text-gray-500">H</span>
				<input
					type="number"
					min="80"
					class="mt-0.5 w-full text-xs rounded-md border border-gray-200 dark:border-gray-700 px-1 py-0.5 bg-white dark:bg-gray-950"
					value={data.height}
					on:input={(e) =>
						updateNodeData(id, {
							height: Math.max(80, Number((e.currentTarget as HTMLInputElement).value) || 220)
						})}
				/>
			</label>
		</div>
		<p class="text-[10px] text-gray-500 dark:text-gray-500 leading-snug">
			{$i18n.t('Decoration only — not executed. Place blocks on top in the canvas.')}
		</p>
	</div>
</div>
