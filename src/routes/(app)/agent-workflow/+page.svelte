<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { get, type Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';
	import { goto } from '$app/navigation';
	import { toast } from 'svelte-sonner';
	import { user } from '$lib/stores';

	import AgentWorkflowPageShell from '$lib/components/agent-workflow/AgentWorkflowPageShell.svelte';
	import {
		migrateLegacyWorkflowIfNeeded,
		listWorkflows,
		createWorkflow,
		deleteWorkflow,
		type WorkflowListEntry
	} from '$lib/components/agent-workflow/workflowListStorage';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	let loaded = false;
	let rows: WorkflowListEntry[] = [];

	function refresh() {
		rows = listWorkflows();
	}

	onMount(() => {
		if ($user === undefined || $user === null) {
			goto('/auth');
			return;
		}
		try {
			migrateLegacyWorkflowIfNeeded(get(i18n).t('My workflow'));
		} catch {
			// ignore
		}
		refresh();
		loaded = true;
	});

	function handleNew() {
		try {
			const def = get(i18n).t('Untitled');
			const entered = window.prompt(get(i18n).t('Name your workflow'), def);
			if (entered === null) return;
			const id = createWorkflow(entered.trim() || def);
			if (!id) {
				toast.error(get(i18n).t('Could not create workflow (storage unavailable).'));
				return;
			}
			goto(`/agent-workflow/${id}`);
		} catch (e) {
			toast.error(e instanceof Error ? e.message : String(e));
		}
	}

	function handleDelete(id: string) {
		if (!confirm(get(i18n).t('Delete workflow?'))) return;
		deleteWorkflow(id);
		refresh();
	}

	function openWorkflow(id: string) {
		goto(`/agent-workflow/${id}`);
	}

	function formatTime(ts: number) {
		try {
			return new Date(ts).toLocaleString();
		} catch {
			return String(ts);
		}
	}
</script>

{#if loaded}
	<AgentWorkflowPageShell title={$i18n.t('Agent workflows')} showBack={false}>
		<div class="h-full overflow-auto p-4 md:p-6">
			<div class="max-w-4xl mx-auto space-y-4">
				<div class="flex flex-wrap items-center justify-between gap-3">
					<p class="text-sm text-gray-600 dark:text-gray-400">
						{$i18n.t('All saved workflows live in this browser (local storage).')}
					</p>
					<button
						type="button"
						class="no-drag-region shrink-0 px-4 py-2 rounded-xl bg-gray-900 text-white dark:bg-gray-100 dark:text-gray-900 text-sm font-medium hover:opacity-90 cursor-pointer"
						on:click={handleNew}
					>
						{$i18n.t('New workflow')}
					</button>
				</div>

				{#if rows.length === 0}
					<div
						class="rounded-2xl border border-dashed border-gray-200 dark:border-gray-700 p-10 text-center text-sm text-gray-500 dark:text-gray-400"
					>
						<p class="mb-4">{$i18n.t('No workflows yet')}</p>
						<button
							type="button"
							class="no-drag-region px-4 py-2 rounded-lg bg-emerald-600 text-white text-sm font-medium hover:bg-emerald-700 cursor-pointer"
							on:click={handleNew}
						>
							{$i18n.t('Create workflow')}
						</button>
					</div>
				{:else}
					<ul class="space-y-2">
						{#each rows as w (w.id)}
							<li>
								<div
									class="flex flex-wrap items-stretch rounded-xl border border-gray-100 dark:border-gray-800 bg-white dark:bg-gray-900 overflow-hidden hover:border-gray-300 dark:hover:border-gray-600 transition"
								>
									<button
										type="button"
										class="no-drag-region flex flex-1 flex-wrap items-center justify-between gap-3 px-4 py-3 text-left min-w-0 cursor-pointer hover:bg-gray-50 dark:hover:bg-gray-800/80"
										on:click={() => openWorkflow(w.id)}
									>
										<div class="min-w-0">
											<div class="font-medium text-gray-900 dark:text-gray-100 truncate">
												{w.name}
											</div>
											<div class="text-xs text-gray-500 dark:text-gray-400 mt-0.5">
												{$i18n.t('Last updated')}: {formatTime(w.updatedAt)}
											</div>
										</div>
										<span
											class="text-sm text-emerald-600 dark:text-emerald-400 font-medium shrink-0"
											>{$i18n.t('Open')}</span
										>
									</button>
									<button
										type="button"
										class="no-drag-region shrink-0 px-4 py-3 text-sm text-red-600 dark:text-red-400 hover:bg-red-950/20 border-l border-gray-100 dark:border-gray-800"
										on:click={() => handleDelete(w.id)}
									>
										{$i18n.t('Delete')}
									</button>
								</div>
							</li>
						{/each}
					</ul>
				{/if}
			</div>
		</div>
	</AgentWorkflowPageShell>
{/if}
