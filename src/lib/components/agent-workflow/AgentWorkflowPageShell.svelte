<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';
	import { goto } from '$app/navigation';
	import { mobile, showSidebar, user } from '$lib/stores';
	import { WEBUI_API_BASE_URL } from '$lib/constants';

	import UserMenu from '$lib/components/layout/Sidebar/UserMenu.svelte';
	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import Sidebar from '$lib/components/icons/Sidebar.svelte';
	import ChevronLeft from '$lib/components/icons/ChevronLeft.svelte';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let title: string;
	export let showBack = false;
</script>

<div
	class="flex flex-col w-full h-screen max-h-[100dvh] transition-width duration-200 ease-in-out {$showSidebar
		? 'md:max-w-[calc(100%-var(--sidebar-width))]'
		: ''} max-w-full"
>
	<nav class="px-2 pt-1.5 backdrop-blur-xl w-full drag-region shrink-0 border-b border-gray-100 dark:border-gray-850">
		<div class="flex items-center justify-between gap-2 pb-1">
			<div class="flex items-center gap-2 min-w-0">
				{#if $mobile}
					<Tooltip content={$showSidebar ? $i18n.t('Close Sidebar') : $i18n.t('Open Sidebar')}>
						<button
							type="button"
							class="cursor-pointer flex rounded-lg hover:bg-gray-100 dark:hover:bg-gray-850 p-1.5"
							on:click={() => showSidebar.set(!$showSidebar)}
							aria-label={$i18n.t('Toggle Sidebar')}
						>
							<Sidebar className="size-5" />
						</button>
					</Tooltip>
				{/if}
				{#if showBack}
					<button
						type="button"
						class="shrink-0 rounded-lg p-1.5 hover:bg-gray-100 dark:hover:bg-gray-850 text-gray-600 dark:text-gray-300"
						on:click={() => goto('/agent-workflow')}
						aria-label={$i18n.t('Back to workflows')}
					>
						<ChevronLeft className="size-5" />
					</button>
				{/if}
				<h1 class="text-lg font-semibold text-gray-900 dark:text-gray-100 truncate">
					{title}
				</h1>
			</div>
			{#if $user !== undefined && $user !== null}
				<UserMenu className="w-[240px]" role={$user?.role} profile={true} help={true}>
					<button
						type="button"
						class="select-none flex rounded-xl p-1.5 hover:bg-gray-50 dark:hover:bg-gray-850 transition"
						aria-label="User Menu"
					>
						<img
							src={`${WEBUI_API_BASE_URL}/users/${$user?.id}/profile/image`}
							class="size-6 object-cover rounded-full"
							alt=""
							draggable="false"
						/>
					</button>
				</UserMenu>
			{/if}
		</div>
	</nav>

	<div
		class="no-drag-region flex-1 min-h-0 w-full overflow-hidden bg-gray-50 dark:bg-gray-950"
	>
		<slot />
	</div>
</div>
