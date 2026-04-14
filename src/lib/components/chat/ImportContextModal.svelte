<script lang="ts">
	import { getContext } from 'svelte';
	import { get } from 'svelte/store';
	import { toast } from 'svelte-sonner';
	import Modal from '$lib/components/common/Modal.svelte';
	import { getChatList } from '$lib/apis/chats';
	import { crossChatImport } from '$lib/apis/crosschat';

	const i18n = getContext('i18n');

	export let show = false;
	export let targetChatId: string;
	export let onImported: () => void = () => {};

	let loading = false;
	let chats: { id: string; title: string }[] = [];
	let selectedId = '';

	const load = async () => {
		loading = true;
		try {
			const list = await getChatList(localStorage.token, null, false, false);
			chats = (list || [])
				.filter((c: { id: string }) => c.id && c.id !== targetChatId)
				.map((c: { id: string; title: string }) => ({ id: c.id, title: c.title || 'Chat' }))
				.slice(0, 80);
		} catch (e) {
			console.error(e);
			toast.error(get(i18n).t('Error'));
		} finally {
			loading = false;
		}
	};

	$: if (show) {
		load();
	}

	const confirm = async () => {
		if (!selectedId || !targetChatId) {
			toast.error(get(i18n).t('Please select a chat'));
			return;
		}
		try {
			await crossChatImport(localStorage.token, {
				target_chat_id: targetChatId,
				source_chat_id: selectedId,
				refresh_snapshot: true
			});
			toast.success(get(i18n).t('Context imported'));
			show = false;
			onImported();
		} catch (e: any) {
			console.error(e);
			toast.error(e?.detail || get(i18n).t('Error'));
		}
	};
</script>

<Modal bind:show size="sm">
	<div class="p-4 dark:text-white">
		<h3 class="text-lg font-medium mb-2">{$i18n.t('Import context from another chat')}</h3>
		<p class="text-sm text-gray-600 dark:text-gray-400 mb-3">
			{$i18n.t('A compact summary will be attached to this chat — not the full transcript.')}
		</p>
		{#if loading}
			<div class="text-sm text-gray-500">{$i18n.t('Loading...')}</div>
		{:else}
			<select
				class="w-full rounded-xl border border-gray-200 dark:border-gray-700 bg-white dark:bg-gray-850 px-3 py-2 text-sm mb-4"
				bind:value={selectedId}
			>
				<option value="">{$i18n.t('Select a chat')}</option>
				{#each chats as c}
					<option value={c.id}>{c.title}</option>
				{/each}
			</select>
		{/if}
		<div class="flex justify-end gap-2">
			<button
				type="button"
				class="px-3 py-1.5 rounded-xl text-sm text-gray-600 dark:text-gray-300"
				on:click={() => (show = false)}
			>
				{$i18n.t('Cancel')}
			</button>
			<button
				type="button"
				class="px-3 py-1.5 rounded-xl text-sm bg-gray-900 dark:bg-white dark:text-gray-900 text-white"
				on:click={confirm}
			>
				{$i18n.t('Import')}
			</button>
		</div>
	</div>
</Modal>
