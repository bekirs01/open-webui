<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';

	import type { AgentWorkflowRunResponse } from '$lib/apis/agentWorkflow';

	import JsonTreeFieldPicker from './JsonTreeFieldPicker.svelte';
	import TriggerFields from './node-forms/TriggerFields.svelte';
	import AgentFields from './node-forms/AgentFields.svelte';
	import IfElseFields from './node-forms/IfElseFields.svelte';
	import TransformFields from './node-forms/TransformFields.svelte';
	import HttpRequestFields from './node-forms/HttpRequestFields.svelte';
	import TelegramFields from './node-forms/TelegramFields.svelte';
	import MergeFields from './node-forms/MergeFields.svelte';
	import GroupFields from './node-forms/GroupFields.svelte';
	import { edges, nodes } from './workflowStore';
	import { getWireFirstItemJson, resolveInputWireText, resolveOutputWireText } from './workflowRunData';
	import { expressionKeyForNode } from './workflowNodeKeys';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let nodeId: string;
	export let lastRun: AgentWorkflowRunResponse | null;
	export let userInput: string;
	export let variant: 'sidebar' | 'modal' = 'sidebar';
	export let hideTitle = false;

	$: node = $nodes.find((n) => n.id === nodeId);
	$: nt = node?.type ?? '';

	$: inputWireText = node
		? resolveInputWireText({
				nodeId: node.id,
				nodeType: nt,
				edges: $edges,
				results: lastRun?.results,
				userInput
			})
		: '';

	$: outputWireText = node ? resolveOutputWireText(node.id, lastRun?.results) : '';

	function outputTreeRoot(): Record<string, unknown> | null {
		if (!node) return null;
		const raw = lastRun?.results?.[node.id];
		return getWireFirstItemJson(raw) ?? null;
	}

	$: outRoot = outputTreeRoot();
	$: outExprKey = node ? expressionKeyForNode(node, $nodes) : '';

	$: nodeRefEntries =
		node != null
			? $nodes.map((n) => {
					const raw = lastRun?.results?.[n.id];
					let sample = getWireFirstItemJson(raw) ?? null;
					if (!sample && n.type === 'trigger') {
						sample = { userInput: userInput || '' };
					}
					return {
						id: n.id,
						key: expressionKeyForNode(n, $nodes),
						sample
					};
				})
			: [];

</script>

{#if node}
	{#if variant === 'modal'}
		<!-- Три колонки: вход | параметры | выход -->
		<div
			class="flex min-h-0 flex-1 flex-col gap-0 overflow-hidden bg-gray-100/90 dark:bg-gray-900 lg:flex-row lg:gap-px"
		>
			<!-- Input -->
			<section
				class="flex min-h-[min(40vh,320px)] min-w-0 flex-1 flex-col overflow-hidden bg-white shadow-sm dark:bg-gray-950 lg:min-h-0 lg:max-w-[min(100%,380px)] lg:flex-[0.95] lg:rounded-none"
			>
				<header
					class="shrink-0 border-b border-emerald-200/80 bg-gradient-to-br from-emerald-50/90 to-white px-3 py-2.5 dark:border-emerald-900/50 dark:from-emerald-950/50 dark:to-gray-950"
				>
					<div class="flex items-center gap-2">
						<span
							class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-sm text-emerald-700 dark:text-emerald-300"
							aria-hidden="true">→</span
						>
						<div>
							<h3 class="text-xs font-semibold uppercase tracking-wide text-emerald-900 dark:text-emerald-100">
								{$i18n.t('Input')}
							</h3>
							<p class="text-[10px] leading-snug text-emerald-800/80 dark:text-emerald-200/70">
								{$i18n.t('Data from workflow nodes — click a field to insert $node')}
							</p>
						</div>
					</div>
				</header>
				<div class="min-h-0 flex-1 overflow-y-auto px-3 py-3">
					<details
						class="group mb-3 overflow-hidden rounded-lg border border-gray-200/90 bg-gray-50/80 dark:border-gray-700 dark:bg-gray-900/50"
					>
						<summary
							class="cursor-pointer list-none px-2.5 py-2 text-[10px] font-medium text-gray-600 marker:hidden dark:text-gray-400 [&::-webkit-details-marker]:hidden"
						>
							<span class="text-gray-400 group-open:rotate-90">▸</span>
							{$i18n.t('Incoming wire (JSON)')}
						</summary>
						<pre
							class="max-h-36 overflow-auto border-t border-gray-200/80 bg-white/90 px-2.5 py-2 font-mono text-[9px] leading-relaxed text-gray-700 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-300"
							>{inputWireText || $i18n.t('Run workflow to populate (or use trigger preview).')}</pre
						>
					</details>
					<div class="space-y-2.5">
						{#each nodeRefEntries as ent (ent.id)}
							<div
								class="rounded-xl border border-gray-200/90 bg-white p-2.5 shadow-sm dark:border-gray-700 dark:bg-gray-900/80"
							>
								<div class="mb-1.5 flex items-center gap-1.5 text-[10px] font-medium text-gray-800 dark:text-gray-100">
									<span class="text-gray-400">{$i18n.t('From')}</span>
									<span class="truncate rounded bg-sky-500/10 px-1.5 py-0.5 font-mono text-sky-800 dark:text-sky-200"
										>{ent.key}</span
									>
								</div>
								<JsonTreeFieldPicker data={ent.sample} nodeExpressionKey={ent.key} />
							</div>
						{/each}
					</div>
				</div>
			</section>

			<!-- Parameters -->
			<section
				class="flex min-h-0 min-w-0 flex-[1.15] flex-col overflow-hidden border-y border-gray-200/80 bg-white shadow-md dark:border-gray-700 dark:bg-gray-950 lg:border-y-0 lg:border-x"
			>
				<header
					class="shrink-0 border-b border-violet-200/80 bg-gradient-to-br from-violet-50/90 to-white px-3 py-2.5 dark:border-violet-900/50 dark:from-violet-950/45 dark:to-gray-950"
				>
					<div class="flex items-center gap-2">
						<span
							class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-violet-500/15 text-sm text-violet-700 dark:text-violet-300"
							aria-hidden="true">⚙</span
						>
						<div>
							<h3 class="text-xs font-semibold uppercase tracking-wide text-violet-900 dark:text-violet-100">
								{$i18n.t('Parameters')}
							</h3>
							<p class="text-[10px] leading-snug text-violet-800/80 dark:text-violet-200/70">
								{$i18n.t('Configure this block')}
							</p>
						</div>
					</div>
				</header>
				<div class="min-h-0 flex-1 overflow-y-auto px-4 py-4">
					{#if nt === 'trigger'}
						<TriggerFields id={node.id} data={node.data as { label: string }} />
					{:else if nt === 'agent'}
						<AgentFields
							id={node.id}
							data={node.data as {
								agentName: string;
								modelId: string;
								task: string;
								mode: 'text' | 'image';
							}}
						/>
					{:else if nt === 'ifElse'}
						<IfElseFields
							id={node.id}
							data={node.data as {
								condition: string;
								conditionMode: 'substring' | 'json' | 'expression';
								conditionExpression?: string;
								jsonPath: string;
								jsonOperator: string;
								compareValue: string;
							}}
						/>
					{:else if nt === 'transform'}
						<TransformFields id={node.id} data={node.data as { template: string }} />
					{:else if nt === 'httpRequest'}
						<HttpRequestFields id={node.id} data={node.data as Record<string, unknown>} />
					{:else if nt === 'telegram'}
						<TelegramFields
							id={node.id}
							data={node.data as {
								credentialMode?: string;
								botToken?: string;
								botTokenEnv?: string;
								chatId?: string;
								messageText?: string;
								parseMode?: string;
							}}
						/>
					{:else if nt === 'merge'}
						<MergeFields id={node.id} data={node.data as { separator: string }} />
					{:else if nt === 'group'}
						<GroupFields
							id={node.id}
							data={node.data as { title: string; width: number; height: number }}
						/>
					{:else}
						<p class="text-xs text-gray-500">{$i18n.t('Unknown node type')}</p>
					{/if}
				</div>
			</section>

			<!-- Output -->
			<section
				class="flex min-h-[min(36vh,280px)] min-w-0 flex-1 flex-col overflow-hidden bg-white shadow-sm dark:bg-gray-950 lg:min-h-0 lg:max-w-[min(100%,380px)] lg:flex-[0.95]"
			>
				<header
					class="shrink-0 border-b border-sky-200/80 bg-gradient-to-br from-sky-50/90 to-white px-3 py-2.5 dark:border-sky-900/50 dark:from-sky-950/50 dark:to-gray-950"
				>
					<div class="flex items-center gap-2">
						<span
							class="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-sky-500/15 text-sm text-sky-700 dark:text-sky-300"
							aria-hidden="true">←</span
						>
						<div>
							<h3 class="text-xs font-semibold uppercase tracking-wide text-sky-900 dark:text-sky-100">
								{$i18n.t('Output')}
							</h3>
							<p class="text-[10px] leading-snug text-sky-800/80 dark:text-sky-200/70">
								{$i18n.t('Result of this node after Run')}
							</p>
						</div>
					</div>
				</header>
				<div class="min-h-0 flex-1 overflow-y-auto px-3 py-3">
					<details
						class="group mb-3 overflow-hidden rounded-lg border border-gray-200/90 bg-gray-50/80 dark:border-gray-700 dark:bg-gray-900/50"
					>
						<summary
							class="cursor-pointer list-none px-2.5 py-2 text-[10px] font-medium text-gray-600 marker:hidden dark:text-gray-400 [&::-webkit-details-marker]:hidden"
						>
							<span class="text-gray-400 group-open:rotate-90">▸</span>
							{$i18n.t('Output wire (JSON)')}
						</summary>
						<pre
							class="max-h-36 overflow-auto border-t border-gray-200/80 bg-white/90 px-2.5 py-2 font-mono text-[9px] leading-relaxed text-gray-700 dark:border-gray-700 dark:bg-gray-950 dark:text-gray-300"
							>{outputWireText || $i18n.t('No output yet — run the workflow.')}</pre
						>
					</details>
					<div
						class="rounded-xl border border-sky-200/60 bg-sky-50/30 p-2.5 dark:border-sky-900/40 dark:bg-sky-950/20"
					>
						<div class="mb-1.5 text-[10px] font-medium text-gray-600 dark:text-gray-400">
							{$i18n.t('Fields')} · <span class="font-mono text-sky-700 dark:text-sky-300">{outExprKey}</span>
						</div>
						<JsonTreeFieldPicker data={outRoot} nodeExpressionKey={outExprKey} />
					</div>
				</div>
			</section>
		</div>
	{:else}
		<!-- Старый компактный вид (сайдбар / узкая колонка) -->
		<div
			class="flex max-h-[min(52vh,520px)] min-h-0 flex-col overflow-hidden border-b border-gray-100 bg-gray-50/90 dark:border-gray-800 dark:bg-gray-900/80"
		>
			{#if !hideTitle}
				<div class="shrink-0 border-b border-gray-100 px-3 py-2 dark:border-gray-800">
					<div class="text-[11px] font-semibold text-gray-800 dark:text-gray-100">
						{$i18n.t('Node settings')}
					</div>
					<div class="mt-0.5 truncate font-mono text-[9px] text-gray-500" title={node.id}>{node.id}</div>
				</div>
			{/if}
			<div class="grid shrink-0 grid-cols-1 gap-2 border-b border-gray-100 px-2 py-2 dark:border-gray-800 sm:grid-cols-2">
				<div class="flex min-h-0 flex-col">
					<div class="mb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
						{$i18n.t('Map from nodes ($node)')}
					</div>
					<details class="mb-2 rounded border border-gray-200 px-2 py-1 dark:border-gray-700">
						<summary class="cursor-pointer text-[10px] text-gray-600 dark:text-gray-300"
							>{$i18n.t('Incoming wire (raw)')}</summary
						>
						<pre
							class="mt-1 max-h-32 overflow-auto font-mono text-[9px] text-gray-700 dark:text-gray-300"
							>{inputWireText || $i18n.t('Run workflow to populate (or use trigger preview).')}</pre
						>
					</details>
					<div class="max-h-40 space-y-2 overflow-y-auto">
						{#each nodeRefEntries as ent (ent.id)}
							<div class="rounded-lg border border-gray-200 p-2 dark:border-gray-700">
								<div class="mb-1 text-[10px] font-medium text-gray-800 dark:text-gray-100">
									{$i18n.t('From')}: <span class="text-sky-600 dark:text-sky-400">{ent.key}</span>
								</div>
								<JsonTreeFieldPicker data={ent.sample} nodeExpressionKey={ent.key} />
							</div>
						{/each}
					</div>
				</div>
				<div class="flex min-h-0 flex-col">
					<div class="mb-1 text-[10px] font-semibold uppercase tracking-wide text-gray-500">
						{$i18n.t('Output')}
					</div>
					<pre
						class="max-h-[28vh] overflow-auto rounded border border-gray-200 bg-white p-1.5 font-mono text-[9px] dark:border-gray-700 dark:bg-gray-950"
						>{outputWireText || $i18n.t('No output yet — run the workflow.')}</pre
					>
					<div class="mt-1 max-h-32 overflow-y-auto">
						<JsonTreeFieldPicker data={outRoot} nodeExpressionKey={outExprKey} />
					</div>
				</div>
			</div>
			<div class="min-h-0 flex-1 space-y-2 overflow-y-auto px-3 py-2">
				<div class="text-[10px] font-semibold uppercase tracking-wide text-gray-600 dark:text-gray-400">
					{$i18n.t('Parameters')}
				</div>
				{#if nt === 'trigger'}
					<TriggerFields id={node.id} data={node.data as { label: string }} />
				{:else if nt === 'agent'}
					<AgentFields
						id={node.id}
						data={node.data as {
							agentName: string;
							modelId: string;
							task: string;
							mode: 'text' | 'image';
						}}
					/>
				{:else if nt === 'ifElse'}
					<IfElseFields
						id={node.id}
						data={node.data as {
							condition: string;
							conditionMode: 'substring' | 'json' | 'expression';
							conditionExpression?: string;
							jsonPath: string;
							jsonOperator: string;
							compareValue: string;
						}}
					/>
				{:else if nt === 'transform'}
					<TransformFields id={node.id} data={node.data as { template: string }} />
				{:else if nt === 'httpRequest'}
					<HttpRequestFields id={node.id} data={node.data as Record<string, unknown>} />
				{:else if nt === 'telegram'}
					<TelegramFields
						id={node.id}
						data={node.data as {
							credentialMode?: string;
							botToken?: string;
							botTokenEnv?: string;
							chatId?: string;
							messageText?: string;
							parseMode?: string;
						}}
					/>
				{:else if nt === 'merge'}
					<MergeFields id={node.id} data={node.data as { separator: string }} />
				{:else if nt === 'group'}
					<GroupFields
						id={node.id}
						data={node.data as { title: string; width: number; height: number }}
					/>
				{:else}
					<p class="text-xs text-gray-500">{$i18n.t('Unknown node type')}</p>
				{/if}
			</div>
		</div>
	{/if}
{/if}
