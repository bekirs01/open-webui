<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as i18nType } from 'i18next';
	import { collabSession } from '$lib/collab.js';

	const i18n: Writable<i18nType> = getContext('i18n');
</script>

{#if $collabSession.roomId}
	<div
		class="flex shrink-0 flex-wrap items-center gap-x-3 gap-y-1 border-b border-gray-200/90 bg-gray-50/95 px-3 py-2 text-xs text-gray-700 backdrop-blur-sm dark:border-gray-700/80 dark:bg-gray-900/90 dark:text-gray-200"
		role="status"
		aria-live="polite"
	>
		<span class="font-semibold text-gray-900 dark:text-gray-100">{$i18n.t('Shared Chat')}</span>
		<span class="hidden sm:inline text-gray-500 dark:text-gray-400">{$i18n.t('Collab room code')}</span>
		<code
			class="rounded bg-gray-200/80 px-1.5 py-0.5 font-mono text-[0.8125rem] text-gray-900 dark:bg-gray-800 dark:text-gray-100"
			>{$collabSession.roomId}</code>
		<span class="inline-flex items-center gap-1.5">
			{#if $collabSession.connection === 'open'}
				<span class="size-2 shrink-0 rounded-full bg-green-500" title={$i18n.t('Collab status connected')}
				></span>
				<span class="text-green-700 dark:text-green-400">{$i18n.t('Collab status connected')}</span>
			{:else if $collabSession.connection === 'connecting'}
				<span
					class="size-2 shrink-0 animate-pulse rounded-full bg-amber-500"
					title={$i18n.t('Collab status connecting')}
				></span>
				<span class="text-amber-700 dark:text-amber-300">{$i18n.t('Collab status connecting')}</span>
			{:else if $collabSession.connection === 'reconnecting'}
				<span
					class="size-2 shrink-0 animate-pulse rounded-full bg-amber-500"
					title={$i18n.t('Collab status reconnecting')}
				></span>
				<span class="text-amber-700 dark:text-amber-300">{$i18n.t('Collab status reconnecting')}</span>
			{:else}
				<span class="size-2 shrink-0 rounded-full bg-gray-400 dark:bg-gray-500"></span>
				<span class="text-gray-500 dark:text-gray-400">{$i18n.t('Collab status offline')}</span>
			{/if}
		</span>
		<span class="text-gray-500 dark:text-gray-500 max-sm:w-full sm:ml-auto">
			{$i18n.t('Collab session hint')}
		</span>
	</div>
{/if}
