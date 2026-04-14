<script lang="ts">
	import { models, showSettings, settings, user, mobile, config } from '$lib/stores';
	import { onMount, tick, getContext } from 'svelte';
	import { toast } from 'svelte-sonner';
	import Selector from './ModelSelector/Selector.svelte';
	import Tooltip from '../common/Tooltip.svelte';

	import { updateUserSettings } from '$lib/apis/users';
	const i18n = getContext('i18n');

	export let selectedModels = [''];
	export let mwsAutoRoutingHint: string | null = null;
	export let disabled = false;

	export let showSetDefault = true;

	const capabilityLabel = (model: Record<string, unknown>) => {
		const catLabel = model?.info?.meta?.mws_ui_category_label;
		if (typeof catLabel === 'string' && catLabel.length) {
			const quality = model?.info?.meta?.mws_quality_tier;
			const speed = model?.info?.meta?.mws_speed_tier;
			let suffix = '';
			if (quality === 'excellent') suffix = ' ★';
			else if (speed === 'fast') suffix = ' ⚡';
			return catLabel + suffix;
		}
		const ui = model?.info?.meta?.mws_ui_label;
		if (typeof ui === 'string' && ui.length) return ui;
		const caps = model?.info?.meta?.mws_capabilities;
		if (Array.isArray(caps) && caps.length) return String(caps[0]);
		const id = String(model?.id ?? '').toLowerCase();
		if (id.includes('whisper') || id.includes('audio')) return 'Audio';
		if (id.includes('vision') || id.includes('llava')) return 'Vision';
		if (id.includes('embed')) return 'Embedding';
		if (id.includes('dall') || id.includes('image')) return 'Image';
		if (id.includes('code') || id.includes('coder')) return 'Code';
		return 'Text';
	};

	const isMwsTagged = (model: Record<string, unknown>) => {
		if (model?.id === 'auto' || model?.id === 'mws:auto') return true;
		const tags = model?.tags;
		if (!Array.isArray(tags)) return false;
		return tags.some((t: unknown) =>
			typeof t === 'object' && t && 'name' in t ? (t as { name?: string }).name === 'mws' : t === 'mws'
		);
	};

	/**
	 * Group models by capability category (from backend metadata) for the picker.
	 * Uses structured mws_ui_category from the capability registry when available,
	 * falls back to heuristic ID matching.
	 */
	const inferModelFamily = (
		model: Record<string, unknown>
	): { key: string; label: string } => {
		const id = String(model?.id ?? '').toLowerCase();

		// Auto sentinel always first
		if (id === 'auto' || id === 'mws:auto') return { key: '0-auto', label: 'Auto' };

		// Use structured category from backend capability registry
		const catSort = model?.info?.meta?.mws_ui_category_sort;
		const catLabel = model?.info?.meta?.mws_ui_category_label;
		if (typeof catSort === 'string' && typeof catLabel === 'string' && catLabel.length) {
			return { key: `${catSort}-${catLabel.toLowerCase().replace(/[\s\/]+/g, '-')}`, label: catLabel };
		}

		// Legacy mws_model_family override
		const metaFam = model?.info?.meta?.mws_model_family;
		if (typeof metaFam === 'string' && metaFam.trim()) {
			const k = metaFam.trim().toLowerCase().replace(/\s+/g, '-');
			return { key: `meta-${k}`, label: metaFam.trim() };
		}

		// Heuristic fallback for models not in the capability registry
		if (id.includes('whisper') || id.includes('audio')) return { key: '6-audio', label: 'Audio / ASR' };
		if (id.includes('bge') || id.includes('embedding')) return { key: '9-embedding', label: 'Embedding' };
		if (id.includes('qwen-image') || id.includes('flux') || id.includes('dall-e') || id.includes('stable-diffusion'))
			return { key: '5-image-generation', label: 'Image Generation' };
		if (id.includes('-vl') || id.includes('vision') || id.includes('llava') || id.includes('cotype'))
			return { key: '4-vision', label: 'Vision' };
		if (id.includes('coder')) return { key: '3-code', label: 'Code' };
		if (id.includes('deepseek-r1') || id.includes('qwq')) return { key: '1-reasoning', label: 'Reasoning' };
		return { key: '2-text', label: 'Text / Chat' };
	};

	const saveDefaultModel = async () => {
		const hasEmptyModel = selectedModels.filter((it) => it === '');
		if (hasEmptyModel.length) {
			toast.error($i18n.t('Choose a model before saving...'));
			return;
		}
		settings.set({ ...$settings, models: selectedModels });
		await updateUserSettings(localStorage.token, { ui: $settings });

		toast.success($i18n.t('Default model updated'));
	};

	const pinModelHandler = async (modelId) => {
		let pinnedModels = $settings?.pinnedModels ?? [];

		if (pinnedModels.includes(modelId)) {
			pinnedModels = pinnedModels.filter((id) => id !== modelId);
		} else {
			pinnedModels = [...new Set([...pinnedModels, modelId])];
		}

		settings.set({ ...$settings, pinnedModels: pinnedModels });
		await updateUserSettings(localStorage.token, { ui: $settings });
	};

	$: if (selectedModels.length > 0 && $models.length > 0) {
		const _selectedModels = selectedModels.map((model) =>
			$models.map((m) => m.id).includes(model) ? model : ''
		);

		if (JSON.stringify(_selectedModels) !== JSON.stringify(selectedModels)) {
			selectedModels = _selectedModels;
		}
	}
</script>

<div class="flex flex-col w-full items-start">
	{#each selectedModels as selectedModel, selectedModelIdx}
		<div class="flex w-full max-w-fit">
			<div class="overflow-hidden w-full">
				<div class="max-w-full {($settings?.highContrastMode ?? false) ? 'm-1' : 'mr-1'}">
					<Selector
						id={`${selectedModelIdx}`}
						placeholder={$i18n.t('Select a model')}
						items={$models
							.map((model) => {
								const fam = inferModelFamily(model);
								return {
									value: model.id,
									label:
										model.id === 'auto' || model.id === 'mws:auto'
											? `${model.name} (Auto)`
											: isMwsTagged(model)
												? `${model.name} · ${capabilityLabel(model)}`
												: model.name,
									model: model,
									groupKey: fam.key,
									groupLabel: fam.label
								};
							})}
						{pinModelHandler}
						bind:value={selectedModel}
					/>
				</div>
			</div>

			{#if $user?.role === 'admin' || ($user?.permissions?.chat?.multiple_models ?? true)}
				{#if selectedModelIdx === 0}
					<div
						class="  self-center mx-1 disabled:text-gray-600 disabled:hover:text-gray-600 -translate-y-[0.5px]"
					>
						<Tooltip content={$i18n.t('Add Model')}>
							<button
								class=" "
								{disabled}
								on:click={() => {
									selectedModels = [...selectedModels, ''];
								}}
								aria-label="Add Model"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="size-3.5"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="M12 6v12m6-6H6" />
								</svg>
							</button>
						</Tooltip>
					</div>
				{:else}
					<div
						class="  self-center mx-1 disabled:text-gray-600 disabled:hover:text-gray-600 -translate-y-[0.5px]"
					>
						<Tooltip content={$i18n.t('Remove Model')}>
							<button
								{disabled}
								on:click={() => {
									selectedModels.splice(selectedModelIdx, 1);
									selectedModels = selectedModels;
								}}
								aria-label="Remove Model"
							>
								<svg
									xmlns="http://www.w3.org/2000/svg"
									fill="none"
									viewBox="0 0 24 24"
									stroke-width="2"
									stroke="currentColor"
									class="size-3"
								>
									<path stroke-linecap="round" stroke-linejoin="round" d="M19.5 12h-15" />
								</svg>
							</button>
						</Tooltip>
					</div>
				{/if}
			{/if}
		</div>
	{/each}
	{#if mwsAutoRoutingHint}
		<div
			class="text-[0.7rem] text-gray-500 dark:text-gray-400 mt-0.5 ml-0.5 max-w-[min(100%,24rem)] truncate"
			title={mwsAutoRoutingHint}
		>
			{mwsAutoRoutingHint}
		</div>
	{/if}
</div>

{#if showSetDefault}
	<div
		class="relative text-left mt-[1px] ml-1 text-[0.7rem] text-gray-600 dark:text-gray-400 font-primary"
	>
		<button on:click={saveDefaultModel}> {$i18n.t('Set as default')}</button>
	</div>
{/if}
