<script lang="ts">
	import { onDestroy, tick } from 'svelte';
	import { get } from 'svelte/store';
	import { goto } from '$app/navigation';
	import Modal from '$lib/components/common/Modal.svelte';
	import { connect, disconnect } from '$lib/collab.js';
	import {
		collabModalTrigger,
		collabRemoteHandler,
		requestCollabInitNewChat
	} from '$lib/stores';

	let showModal = false;
	let lastCollabTrigger = 0;
	let tab: 'create' | 'join' = 'create';
	let joinInput = '';
	let createdRoomId = '';
	/** Mirrors joined room for badge (set on join; cleared on leave). */
	let badgeRoomId = '';

	function randomRoomId(): string {
		const chars = 'abcdefghijklmnopqrstuvwxyz0123456789';
		const out = new Uint8Array(6);
		crypto.getRandomValues(out);
		let s = '';
		for (let i = 0; i < 6; i++) s += chars[out[i] % chars.length];
		return s;
	}

	function ensureCreatedId() {
		if (!createdRoomId) createdRoomId = randomRoomId();
	}

	async function enterRoom(roomId: string) {
		const id = roomId.trim().toLowerCase().slice(0, 64);
		if (!id) return;
		badgeRoomId = id;
		connect(id, (data) => {
			const h = get(collabRemoteHandler);
			if (h) void h(data as Record<string, unknown>);
		});
		showModal = false;
		joinInput = '';

		// Реальная навигация на главную: replaceState в initNewChat не меняет маршрут SvelteKit,
		// из‑за этого на `/c/...` старый chatIdProp оставался и перезагружал беседу.
		const path = typeof window !== 'undefined' ? window.location.pathname : '';
		if (path !== '/') {
			await goto('/');
		}
		await tick();
		await new Promise<void>((r) => setTimeout(r, 0));
		requestCollabInitNewChat();
	}

	function leaveRoom() {
		disconnect();
		badgeRoomId = '';
		createdRoomId = '';
		joinInput = '';
	}

	function copyRoom(id: string) {
		if (!id || typeof navigator === 'undefined' || !navigator.clipboard?.writeText) return;
		navigator.clipboard.writeText(id).catch(() => {});
	}

	$: if (showModal && tab === 'create') ensureCreatedId();

	$: {
		const t = $collabModalTrigger;
		if (t > lastCollabTrigger) {
			lastCollabTrigger = t;
			showModal = true;
		}
	}

	onDestroy(() => {
		disconnect();
	});
</script>

<Modal bind:show={showModal} size="sm" containerClassName="p-4">
	<div class="modal-content flex flex-col gap-3 p-4">
		<h2 class="text-lg font-medium text-gray-900 dark:text-gray-100">Совместный чат</h2>
		{#if badgeRoomId}
			<div
				class="flex min-w-0 items-center justify-between gap-3 rounded-xl border border-gray-200/80 bg-gray-50 px-3 py-2 dark:border-gray-600/80 dark:bg-gray-800/80"
			>
				<span
					class="min-w-0 truncate font-mono text-sm tabular-nums text-gray-800 dark:text-gray-100"
					title="Совместная комната"
				>
					● {badgeRoomId}
				</span>
				<button
					type="button"
					class="shrink-0 rounded-lg px-2 py-1 text-sm text-gray-600 underline decoration-gray-400 underline-offset-2 hover:bg-gray-200/80 hover:text-gray-900 dark:text-gray-300 dark:hover:bg-gray-700 dark:hover:text-white"
					on:click={leaveRoom}
				>
					Выйти
				</button>
			</div>
		{/if}
		<div class="flex gap-2 border-b border-gray-200 pb-2 dark:border-gray-700">
			<button
				type="button"
				class="rounded px-2 py-1 {tab === 'create'
					? 'bg-gray-200 dark:bg-gray-700'
					: 'hover:bg-gray-100 dark:hover:bg-gray-800'}"
				on:click={() => {
					tab = 'create';
				}}>Создать комнату</button>
			<button
				type="button"
				class="rounded px-2 py-1 {tab === 'join'
					? 'bg-gray-200 dark:bg-gray-700'
					: 'hover:bg-gray-100 dark:hover:bg-gray-800'}"
				on:click={() => {
					tab = 'join';
				}}>Войти в комнату</button>
		</div>

		{#if tab === 'create'}
			<p class="text-sm text-gray-600 dark:text-gray-400">
				Создайте код и отправьте его собеседнику любым способом.
			</p>
			<div class="flex items-center gap-2">
				<pre
					class="flex-1 overflow-x-auto rounded bg-gray-100 p-2 font-mono text-sm dark:bg-gray-800">{createdRoomId ||
						'······'}</pre>
				<button
					type="button"
					class="rounded border border-gray-300 px-2 py-1 text-sm dark:border-gray-600"
					on:click={() => copyRoom(createdRoomId)}>Копировать</button>
			</div>
			<button
				type="button"
				class="w-full rounded-lg bg-gray-900 py-2 text-sm text-white dark:bg-gray-100 dark:text-gray-900"
				on:click={() => {
					ensureCreatedId();
					enterRoom(createdRoomId);
				}}>Войти в эту комнату</button>
		{:else}
			<label class="text-sm text-gray-600 dark:text-gray-400" for="collab-join-input">Код комнаты</label>
			<input
				id="collab-join-input"
				class="w-full rounded border border-gray-300 bg-white px-2 py-1.5 font-mono text-sm dark:border-gray-600 dark:bg-gray-900"
				bind:value={joinInput}
				maxlength="64"
				placeholder="abcdef"
				on:keydown={(e) => {
					if (e.key === 'Enter') enterRoom(joinInput);
				}}
			/>
			<button
				type="button"
				class="w-full rounded-lg bg-gray-900 py-2 text-sm text-white dark:bg-gray-100 dark:text-gray-900"
				on:click={() => enterRoom(joinInput)}>Войти</button>
		{/if}
	</div>
</Modal>
