<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import {
		COMMON_JSON_FIELD_PRESETS,
		buildComparisonFormula,
		CMP_OPS,
		formulaJsonField,
		sanitizeJsonFieldPath,
		templateJsonField
	} from './expressionUi';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	/** Append snippet at cursor or end — parent owns the textarea value */
	export let onInsert: (snippet: string) => void;

	/** template = {{$json.x}} ; condition = ={{$json.x}} or builder */
	export let flavor: 'template' | 'condition' = 'template';

	let fieldInput = '';
	let cmpOp: (typeof CMP_OPS)[number] = '>';
	let cmpVal = '18';

	function insert(s: string) {
		if (s) onInsert(s);
	}

	function insertFieldTemplate() {
		const s = templateJsonField(fieldInput);
		if (s) insert(s);
	}

	function insertFieldFormula() {
		const s = formulaJsonField(fieldInput);
		if (s) insert(s);
	}

	function insertComparison() {
		const s = buildComparisonFormula(fieldInput, cmpOp, cmpVal);
		if (s) insert(s);
	}
</script>

<div
	class="rounded-lg border border-gray-200/80 dark:border-gray-600/80 bg-gray-50/90 dark:bg-gray-900/50 p-2 space-y-2"
>
	<p class="text-[10px] text-gray-600 dark:text-gray-400 leading-snug">
		{$i18n.t('Insert values without typing JSON: pick a preset or enter a field name (e.g. age or user.name).')}
	</p>

	<div class="flex flex-wrap gap-1">
		<button
			type="button"
			class="text-[10px] px-1.5 py-0.5 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 hover:bg-violet-50 dark:hover:bg-violet-950/50"
			on:click={() => insert('{{$itemIndex}}')}
		>
			$itemIndex
		</button>
		<button
			type="button"
			class="text-[10px] px-1.5 py-0.5 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 hover:bg-violet-50 dark:hover:bg-violet-950/50"
			on:click={() => insert('{{$input.length}}')}
		>
			$input.length
		</button>
		{#each COMMON_JSON_FIELD_PRESETS as p (p.key)}
			<button
				type="button"
				class="text-[10px] px-1.5 py-0.5 rounded bg-white dark:bg-gray-800 border border-gray-200 dark:border-gray-600 hover:bg-violet-50 dark:hover:bg-violet-950/50"
				title={$i18n.t(p.labelKey)}
				on:click={() =>
					insert(flavor === 'condition' ? formulaJsonField(p.key) : templateJsonField(p.key))}
			>
				{p.key}
			</button>
		{/each}
	</div>

	<div class="flex flex-wrap items-end gap-1">
		<label class="flex-1 min-w-[100px]">
			<span class="text-[9px] uppercase text-gray-500">{$i18n.t('Field path')}</span>
			<input
				type="text"
				class="mt-0.5 w-full text-[11px] font-mono rounded border border-gray-200 dark:border-gray-600 px-1.5 py-1 bg-white dark:bg-gray-900"
				placeholder="age / user.name"
				bind:value={fieldInput}
			/>
		</label>
		<button
			type="button"
			class="text-[10px] px-2 py-1 rounded bg-sky-100 dark:bg-sky-900/50 border border-sky-200 dark:border-sky-800"
			title={$i18n.t('Insert as template brace {{$json.field}}')}
			on:click={insertFieldTemplate}
		>
			{$i18n.t('Template')}
		</button>
		{#if flavor === 'condition'}
			<button
				type="button"
				class="text-[10px] px-2 py-1 rounded bg-violet-100 dark:bg-violet-900/40 border border-violet-200 dark:border-violet-800"
				title={$i18n.t('Insert as formula ={{ ... }} (boolean / compare)')}
				on:click={insertFieldFormula}
			>
				{$i18n.t('Formula')}
			</button>
		{/if}
	</div>

	{#if flavor === 'condition'}
		<div class="flex flex-wrap items-end gap-1 pt-1 border-t border-gray-200/80 dark:border-gray-600/60">
			<span class="text-[9px] text-gray-500 w-full">{$i18n.t('Quick compare (numbers or text)')}</span>
			<select
				class="text-[10px] rounded border border-gray-200 dark:border-gray-600 px-1 py-1 bg-white dark:bg-gray-900"
				bind:value={cmpOp}
			>
				{#each CMP_OPS as op (op)}
					<option value={op}>{op}</option>
				{/each}
			</select>
			<input
				type="text"
				class="flex-1 min-w-[48px] text-[11px] font-mono rounded border border-gray-200 dark:border-gray-600 px-1.5 py-1 bg-white dark:bg-gray-900"
				placeholder="18 / ok"
				bind:value={cmpVal}
			/>
			<button
				type="button"
				class="text-[10px] px-2 py-1 rounded bg-emerald-100 dark:bg-emerald-900/40 border border-emerald-200 dark:border-emerald-800"
				on:click={insertComparison}
			>
				{$i18n.t('Insert condition')}
			</button>
		</div>
	{/if}
</div>
