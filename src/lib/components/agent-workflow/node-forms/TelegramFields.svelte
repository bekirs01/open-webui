<script lang="ts">
	import { getContext, tick } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import ExpressionInsertBar from '../ExpressionInsertBar.svelte';
	import { insertAtCaret } from '../expressionUi';
	import { updateNodeData } from '../workflowStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let id: string;
	export let data: {
		credentialMode?: string;
		botToken?: string;
		botTokenEnv?: string;
		chatId?: string;
		messageText?: string;
		parseMode?: string;
	};

	let msgEl: HTMLTextAreaElement | undefined;
	let chatEl: HTMLInputElement | undefined;

	async function insertIntoMessage(snippet: string) {
		const cur = data.messageText ?? '';
		const { next, caret } = insertAtCaret(cur, msgEl?.selectionStart, msgEl?.selectionEnd, snippet);
		updateNodeData(id, { messageText: next });
		await tick();
		msgEl?.focus();
		msgEl?.setSelectionRange(caret, caret);
	}
</script>

<p class="text-[11px] text-sky-900/85 dark:text-sky-200/90">
	{$i18n.t(
		'Sends a Telegram message via Bot API (sendMessage). Prefer env TELEGRAM_BOT_TOKEN; inline token is stored in the workflow JSON.'
	)}
</p>

<label class="block mb-2">
	<span class="text-[10px] uppercase text-sky-800/80">{$i18n.t('Credentials')}</span>
	<select
		class="mt-1 w-full text-sm rounded-lg border border-sky-200 dark:border-sky-800 px-2 py-1.5 bg-white dark:bg-gray-900"
		value={data.credentialMode === 'inline' ? 'inline' : 'env'}
		on:change={(e) =>
			updateNodeData(id, { credentialMode: (e.currentTarget as HTMLSelectElement).value })}
	>
		<option value="env">{$i18n.t('Environment variable')}</option>
		<option value="inline">{$i18n.t('Inline (demo only)')}</option>
	</select>
</label>

{#if data.credentialMode === 'inline'}
	<label class="block mb-2">
		<span class="text-[10px] uppercase text-sky-800/80">{$i18n.t('Bot token')}</span>
		<input
			type="password"
			autocomplete="off"
			class="mt-1 w-full font-mono text-xs rounded-lg border border-sky-200 dark:border-sky-800 px-2 py-1.5 bg-white dark:bg-gray-900"
			value={data.botToken ?? ''}
			on:input={(e) => updateNodeData(id, { botToken: e.currentTarget.value })}
		/>
	</label>
{:else}
	<label class="block mb-2">
		<span class="text-[10px] uppercase text-sky-800/80">{$i18n.t('Env var name')}</span>
		<input
			type="text"
			class="mt-1 w-full font-mono text-xs rounded-lg border border-sky-200 dark:border-sky-800 px-2 py-1.5 bg-white dark:bg-gray-900"
			value={data.botTokenEnv ?? 'TELEGRAM_BOT_TOKEN'}
			on:input={(e) => updateNodeData(id, { botTokenEnv: e.currentTarget.value })}
		/>
	</label>
{/if}

<label class="block mb-2">
	<span class="text-[10px] uppercase text-sky-800/80">{$i18n.t('Chat ID')}</span>
	<input
		bind:this={chatEl}
		type="text"
		class="mt-1 w-full font-mono text-xs rounded-lg border border-sky-200 dark:border-sky-800 px-2 py-1.5 bg-white dark:bg-gray-900"
		value={data.chatId ?? ''}
		placeholder="123456789"
		on:input={(e) => updateNodeData(id, { chatId: e.currentTarget.value })}
	/>
</label>

<div class="mb-1 flex flex-wrap items-center gap-2">
	<span class="text-[10px] uppercase text-sky-800/80">{$i18n.t('Message')}</span>
	<ExpressionInsertBar flavor="template" onInsert={insertIntoMessage} />
</div>
<label class="block mb-2">
	<textarea
		bind:this={msgEl}
		rows="4"
		class="w-full font-mono text-xs rounded-lg border border-sky-200 dark:border-sky-800 px-2 py-1.5 bg-white dark:bg-gray-900"
		value={data.messageText ?? '{{input}}'}
		on:input={(e) => updateNodeData(id, { messageText: e.currentTarget.value })}
	></textarea>
</label>

<label class="block mb-2">
	<span class="text-[10px] uppercase text-sky-800/80">{$i18n.t('Parse mode (optional)')}</span>
	<select
		class="mt-1 w-full text-sm rounded-lg border border-sky-200 dark:border-sky-800 px-2 py-1.5 bg-white dark:bg-gray-900"
		value={data.parseMode ?? ''}
		on:change={(e) => updateNodeData(id, { parseMode: (e.currentTarget as HTMLSelectElement).value })}
	>
		<option value="">{$i18n.t('None')}</option>
		<option value="HTML">HTML</option>
		<option value="MarkdownV2">MarkdownV2</option>
	</select>
</label>
