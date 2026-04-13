<script lang="ts">
	import { Handle, Position } from '@xyflow/svelte';
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { models } from '$lib/stores';
	import { patchAgentNode, setStartNode, startNodeId } from './workflowStore';
	import { runStepHighlightId } from './editorUiStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;
	export let selected = false;

	type Data = {
		agentName: string;
		modelId: string;
		task: string;
		mode: 'text' | 'image';
		disabled?: boolean;
	};

	export let data: Data;

	$: isStart = id === $startNodeId;
	$: runStep = $runStepHighlightId === id;
	$: isDisabled = Boolean(data.disabled);
</script>

<div
	class="rounded-xl border bg-white shadow-md dark:bg-gray-900 w-[300px] max-w-[90vw] transition-shadow {isDisabled
		? 'opacity-60 saturate-50'
		: ''} {runStep
		? 'ring-2 ring-cyan-400 border-cyan-500/80'
		: selected
			? 'ring-2 ring-emerald-500 border-emerald-400'
			: 'border-gray-200 dark:border-gray-700'}"
>
	<div
		class="flex items-center justify-between gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-800"
	>
		<span class="text-xs font-medium text-gray-700 dark:text-gray-200 truncate">
			{$i18n.t('Agent node')}
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
		<label class="block">
			<span class="text-[10px] uppercase tracking-wide text-gray-500">{$i18n.t('Name')}</span>
			<input
				class="mt-1 w-full text-sm rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 px-2 py-1.5"
				placeholder={$i18n.t('Agent name (optional)')}
				value={data.agentName}
				on:input={(e) =>
					patchAgentNode(id, 'agentName', (e.currentTarget as HTMLInputElement).value)}
			/>
		</label>

		<label class="block">
			<span class="text-[10px] uppercase tracking-wide text-gray-500">{$i18n.t('Model')}</span>
			<select
				class="mt-1 w-full text-sm rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 px-2 py-1.5"
				value={data.modelId}
				on:change={(e) =>
					patchAgentNode(id, 'modelId', (e.currentTarget as HTMLSelectElement).value)}
			>
				<option value="">—</option>
				{#each $models ?? [] as m (m.id)}
					<option value={m.id}>{m.name ?? m.id}</option>
				{/each}
			</select>
		</label>

		<label class="block">
			<span class="text-[10px] uppercase tracking-wide text-gray-500">{$i18n.t('Node mode')}</span>
			<select
				class="mt-1 w-full text-sm rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 px-2 py-1.5"
				value={data.mode}
				on:change={(e) =>
					patchAgentNode(id, 'mode', (e.currentTarget as HTMLSelectElement).value)}
			>
				<option value="text">{$i18n.t('Text LLM')}</option>
				<option value="image">{$i18n.t('Image generation')}</option>
			</select>
		</label>

		<label class="block">
			<span class="text-[10px] uppercase tracking-wide text-gray-500"
				>{data.mode === 'image'
					? $i18n.t('Instruction for image prompt (optional)')
					: $i18n.t('Task for this agent')}</span
			>
			<textarea
				class="mt-1 w-full text-sm rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 px-2 py-1.5 min-h-[72px] resize-y"
				placeholder={data.mode === 'image'
					? $i18n.t(
							'Leave empty to use the previous step text as the image prompt. If set, a text model refines the prompt using this instruction.'
						)
					: $i18n.t('Instruction for this step…')}
				value={data.task}
				on:input={(e) =>
					patchAgentNode(id, 'task', (e.currentTarget as HTMLTextAreaElement).value)}
			></textarea>
		</label>
	</div>

	<Handle
		type="target"
		position={Position.Left}
		class="!w-2.5 !h-2.5 !bg-gray-400 dark:!bg-gray-500 !border-0"
	/>
	<Handle
		type="source"
		position={Position.Right}
		class="!w-2.5 !h-2.5 !bg-gray-400 dark:!bg-gray-500 !border-0"
	/>
</div>
