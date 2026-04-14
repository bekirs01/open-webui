<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import { models } from '$lib/stores';
	import { patchAgentNode } from '../workflowStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;

	type Data = {
		agentName: string;
		modelId: string;
		task: string;
		mode: 'text' | 'image';
		disabled?: boolean;
	};
	export let data: Data;
</script>

<div class="space-y-2">
	<label class="block">
		<span class="text-[10px] uppercase tracking-wide text-gray-500">{$i18n.t('Name')}</span>
		<input
			class="mt-1 w-full text-sm rounded-lg bg-gray-50 dark:bg-gray-850 border border-gray-200 dark:border-gray-700 px-2 py-1.5"
			placeholder={$i18n.t('Agent name (optional)')}
			value={data.agentName}
			on:input={(e) => patchAgentNode(id, 'agentName', (e.currentTarget as HTMLInputElement).value)}
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
			on:change={(e) => patchAgentNode(id, 'mode', (e.currentTarget as HTMLSelectElement).value)}
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
			on:input={(e) => patchAgentNode(id, 'task', (e.currentTarget as HTMLTextAreaElement).value)}
		></textarea>
	</label>
</div>
