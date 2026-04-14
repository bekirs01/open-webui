<script>
	import { getContext } from 'svelte';
	const i18n = getContext('i18n');
	import WebSearchResults from '../WebSearchResults.svelte';
	import Search from '$lib/components/icons/Search.svelte';
	import { t } from 'i18next';

	export let status = null;
	export let done = false;
</script>

{#if !status?.hidden}
	<div class="status-description flex items-center gap-2 py-0.5 w-full text-left">
		{#if status?.action === 'web_search' && (status?.urls || status?.items)}
			<WebSearchResults {status}>
				<div class="flex flex-col justify-center -space-y-0.5">
					<div
						class="{(done || status?.done) === false
							? 'shimmer'
							: ''} text-base line-clamp-1 text-wrap"
					>
						{#if status?.description?.includes('{{count}}')}
							{$i18n.t(status?.description, {
								count: (status?.urls || status?.items).length
							})}
						{:else if status?.description === 'No search query generated'}
							{$i18n.t('No search query generated')}
						{:else if status?.description === 'Generating search query'}
							{$i18n.t('Generating search query')}
						{:else}
							{status?.description}
						{/if}
					</div>
				</div>
			</WebSearchResults>
		{:else if status?.action === 'knowledge_search'}
			<div class="flex flex-col justify-center -space-y-0.5">
				<div
					class="{(done || status?.done) === false
						? 'shimmer'
						: ''} text-gray-500 dark:text-gray-500 text-base line-clamp-1 text-wrap"
				>
					{$i18n.t(`Searching Knowledge for "{{searchQuery}}"`, {
						searchQuery: status.query
					})}
				</div>
			</div>
	{:else if status?.action === 'deep_thinking'}
		<div class="flex flex-col justify-center">
			<div
				class="{(done || status?.done) === false
					? 'shimmer'
					: ''} text-gray-700 dark:text-gray-300 text-base font-medium"
			>
				🧠 {$i18n.t('Deep thinking mode active')}
			</div>
			{#if (done || status?.done) === false}
				<div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
					{$i18n.t('Analyzing your question in depth for a more comprehensive answer')}
				</div>
			{/if}
		</div>
	{:else if status?.action === 'web_search_queries_generated' && status?.queries}
		<div class="flex flex-col justify-center">
			<div
				class="{(done || status?.done) === false
					? 'shimmer'
					: ''} text-gray-700 dark:text-gray-300 text-base font-medium"
			>
				🔎 {$i18n.t(`Searching`)}...
			</div>

			<div class="flex gap-1.5 flex-wrap mt-2">
				{#each status.queries as query, idx (query)}
					<div
						class="bg-blue-50 dark:bg-blue-900/30 border border-blue-200 dark:border-blue-800 flex rounded-lg py-1.5 px-2.5 items-center gap-1.5 text-xs text-blue-700 dark:text-blue-300"
					>
						<div>
							<Search className="size-3" />
						</div>

						<span class="line-clamp-1 font-medium">
							{query}
						</span>
					</div>
				{/each}
			</div>
		</div>
		{:else if status?.action === 'queries_generated' && status?.queries}
			<div class="flex flex-col justify-center -space-y-0.5">
				<div
					class="{(done || status?.done) === false
						? 'shimmer'
						: ''} text-gray-500 dark:text-gray-500 text-base line-clamp-1 text-wrap"
				>
					{$i18n.t(`Querying`)}
				</div>

				<div class=" flex gap-1 flex-wrap mt-2">
					{#each status.queries as query, idx (query)}
						<div
							class="bg-gray-50 dark:bg-gray-850 flex rounded-lg py-1 px-2 items-center gap-1 text-xs"
						>
							<div>
								<Search className="size-3" />
							</div>

							<span class="line-clamp-1">
								{query}
							</span>
						</div>
					{/each}
				</div>
			</div>
		{:else if status?.action === 'sources_retrieved' && status?.count !== undefined}
			<div class="flex flex-col justify-center -space-y-0.5">
				<div
					class="{(done || status?.done) === false
						? 'shimmer'
						: ''} text-gray-500 dark:text-gray-500 text-base line-clamp-1 text-wrap"
				>
					{#if status.count === 0}
						{$i18n.t('No sources found')}
					{:else if status.count === 1}
						{$i18n.t('Retrieved 1 source')}
					{:else}
						<!-- {$i18n.t('Source')} -->
						<!-- {$i18n.t('No source available')} -->
						<!-- {$i18n.t('No distance available')} -->
						<!-- {$i18n.t('Retrieved {{count}} sources')} -->
						{$i18n.t('Retrieved {{count}} sources', {
							count: status.count
						})}
					{/if}
				</div>
			</div>
	{:else}
		<div class="flex flex-col justify-center -space-y-0.5">
			{#if status?.description === 'Searching the web'}
				<div
					class="{(done || status?.done) === false
						? 'shimmer'
						: ''} text-gray-700 dark:text-gray-300 text-base font-medium"
				>
					🔍 {$i18n.t('Searching the web')}...
				</div>
				{#if (done || status?.done) === false}
					<div class="text-xs text-gray-400 dark:text-gray-500 mt-0.5">
						{$i18n.t('Please wait while results are being fetched')}
					</div>
				{/if}
			{:else}
				<div
					class="{(done || status?.done) === false
						? 'shimmer'
						: ''} text-gray-500 dark:text-gray-500 text-base line-clamp-1 text-wrap"
				>
					{#if status?.description?.includes('{{searchQuery}}')}
						{$i18n.t(status?.description, {
							searchQuery: status?.query
						})}
					{:else if status?.description === 'No search query generated'}
						{$i18n.t('No search query generated')}
					{:else if status?.description === 'Generating search query'}
						{$i18n.t('Generating search query')}
					{:else}
						{status?.description}
					{/if}
				</div>
			{/if}
		</div>
	{/if}
	</div>
{/if}
