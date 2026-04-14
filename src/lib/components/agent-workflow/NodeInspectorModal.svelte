<script lang="ts">
	import { browser } from '$app/environment';
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import type { AgentWorkflowRunResponse } from '$lib/apis/agentWorkflow';

	import NodeInspectorPanel from './NodeInspectorPanel.svelte';
	import { closeNodeInspector } from './editorUiStore';
	import { NODE_REGISTRY, type FlowNodeTypeId } from './nodeRegistry';
	import { nodes } from './workflowStore';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let nodeId: string;
	export let lastRun: AgentWorkflowRunResponse | null;
	export let userInput: string;

	$: modalNode = $nodes.find((n) => n.id === nodeId);
	$: modalType = modalNode?.type as FlowNodeTypeId | undefined;
	$: reg =
		modalType && modalType in NODE_REGISTRY ? NODE_REGISTRY[modalType] : null;

	function close() {
		closeNodeInspector();
	}

	function onKeyDown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			close();
		}
	}

	onMount(() => {
		if (!browser) return;
		document.addEventListener('keydown', onKeyDown);
		const prev = document.body.style.overflow;
		document.body.style.overflow = 'hidden';
		return () => {
			document.removeEventListener('keydown', onKeyDown);
			document.body.style.overflow = prev;
		};
	});
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<div
	class="fixed inset-0 z-[300] flex items-center justify-center p-2 sm:p-4 md:p-5"
	role="presentation"
>
	<button
		type="button"
		class="absolute inset-0 cursor-default border-0 bg-black/45 p-0 backdrop-blur-[2px] dark:bg-black/55"
		aria-label={$i18n.t('Close')}
		on:click={close}
	></button>
	<div
		class="relative z-[1] flex max-h-[min(92vh,900px)] w-full max-w-[min(96rem,calc(100vw-1rem))] min-h-0 flex-col overflow-hidden rounded-2xl border border-gray-200/90 bg-white shadow-[0_25px_80px_-12px_rgba(0,0,0,0.25)] dark:border-gray-600/80 dark:bg-gray-950 dark:shadow-[0_25px_80px_-12px_rgba(0,0,0,0.5)]"
		role="dialog"
		aria-modal="true"
		aria-labelledby="agent-wf-node-settings-title"
		on:click|stopPropagation
	>
		<div
			class="flex shrink-0 items-start gap-3 border-b border-gray-200/80 bg-gradient-to-b from-slate-50/95 to-white px-4 py-3.5 dark:border-gray-800 dark:from-gray-900 dark:to-gray-950 sm:px-5"
		>
			{#if reg?.icon}
				<span
					class="mt-0.5 flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border border-gray-200/80 bg-white text-xl shadow-sm dark:border-gray-700 dark:bg-gray-900"
					aria-hidden="true">{reg.icon}</span
				>
			{/if}
			<div class="min-w-0 flex-1">
				<p class="text-[10px] font-semibold uppercase tracking-wider text-gray-400 dark:text-gray-500">
					{$i18n.t('Node settings')}
				</p>
				<h2
					id="agent-wf-node-settings-title"
					class="mt-0.5 text-base font-semibold leading-tight text-gray-900 dark:text-gray-50"
				>
					{reg ? $i18n.t(reg.labelKey) : $i18n.t('Block')}
				</h2>
				<p class="mt-1 truncate font-mono text-[10px] text-gray-500 dark:text-gray-400" title={nodeId}>
					{nodeId}
				</p>
			</div>
			<button
				type="button"
				class="rounded-xl p-2.5 text-gray-500 transition-colors hover:bg-gray-100 hover:text-gray-900 dark:hover:bg-gray-800 dark:hover:text-gray-100"
				aria-label={$i18n.t('Close')}
				on:click={close}
			>
				<span class="block text-xl leading-none" aria-hidden="true">×</span>
			</button>
		</div>
		<div class="flex min-h-0 min-h-[min(70vh,640px)] flex-1 flex-col overflow-hidden lg:min-h-[520px]">
			<NodeInspectorPanel {nodeId} {lastRun} {userInput} variant="modal" hideTitle={true} />
		</div>
	</div>
</div>
