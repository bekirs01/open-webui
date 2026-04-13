<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import { browser } from '$app/environment';
	import { goto } from '$app/navigation';
	import { get } from 'svelte/store';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';
	import type { ColorMode } from '@xyflow/svelte';
	import { toast } from 'svelte-sonner';
	import DOMPurify from 'dompurify';
	import { marked } from 'marked';

	import { theme, models } from '$lib/stores';
	import { generateWorkflowFromDescription, suggestNodeFieldsFromContext } from './workflowAiGenerate';
	import { modelLabel, pickDefaultWorkflowAiModelId } from './workflowAiModelPick';
	import { runAgentWorkflow, type AgentWorkflowRunResponse } from '$lib/apis/agentWorkflow';
	import {
		SvelteFlow,
		SvelteFlowProvider,
		Background,
		BackgroundVariant,
		addEdge,
		type Connection,
		type EdgeTypes,
		type NodeTypes
	} from '@xyflow/svelte';
	import '@xyflow/svelte/dist/style.css';

	import AgentNode from './AgentNode.svelte';
	import TriggerNode from './TriggerNode.svelte';
	import IfElseNode from './IfElseNode.svelte';
	import TransformNode from './TransformNode.svelte';
	import HttpRequestNode from './HttpRequestNode.svelte';
	import MergeNode from './MergeNode.svelte';
	import GroupNode from './GroupNode.svelte';
	import WorkflowEdge from './WorkflowEdge.svelte';
	import FlowCanvasExtras from './FlowCanvasExtras.svelte';
	import NodePicker from './NodePicker.svelte';

	import type { AgentWorkflowV1 } from './types';
	import { validateAgentWorkflow } from './validate';
	import {
		nodes,
		edges,
		startNodeId,
		addNodeAt
	} from './workflowStore';
	import { clearWorkflowHistory, pushUndoSnapshot } from './workflowHistory';
	import { runStepHighlightId } from './editorUiStore';
	import { buildWorkflowV1, jsonToFlowNode, normalizeWorkflowForLoad } from './serialization';
	import { isValidWorkflowConnection } from './connectionRules';
	import { connectEndBridge } from './connectBridge';
	import { NODE_REGISTRY, type FlowNodeTypeId } from './nodeRegistry';
	import {
		workflowStorageKey,
		touchWorkflowUpdated,
		getWorkflowEntry,
		ensureWorkflowInIndex
	} from './workflowListStorage';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	export let workflowId: string;

	$: storageKey = workflowStorageKey(workflowId);

	const nodeTypes = {
		trigger: TriggerNode,
		agent: AgentNode,
		ifElse: IfElseNode,
		transform: TransformNode,
		httpRequest: HttpRequestNode,
		merge: MergeNode,
		group: GroupNode
	} as unknown as NodeTypes;

	const edgeTypes = {
		workflow: WorkflowEdge
	} as unknown as EdgeTypes;

	let userInput = '';
	let running = false;
	let runError: string | null = null;
	let lastRun: AgentWorkflowRunResponse | null = null;

	let canvasExtras: FlowCanvasExtras;

	const firstModelId = () => get(models)?.[0]?.id ?? '';

	let validationDebouncedCode: string | null = null;
	let validationTimer: ReturnType<typeof setTimeout> | undefined;
	let runHighlightTimer: ReturnType<typeof setInterval> | null = null;

	let aiDraftDescription = '';
	/** Empty string = use automatic pick (text/JSON-suitable model, not image-gen). */
	let aiModelManual = '';
	let aiBusy = false;
	let aiHintsText = '';

	$: aiAutoModelId = pickDefaultWorkflowAiModelId($models ?? []) || firstModelId() || '';
	$: effectiveAiModelId = (aiModelManual || aiAutoModelId).trim();
	$: {
		const list = $models ?? [];
		if (aiModelManual && !list.some((m) => m.id === aiModelManual)) {
			aiModelManual = '';
		}
	}

	function buildWf(): AgentWorkflowV1 {
		return buildWorkflowV1(get(nodes), get(edges), get(startNodeId));
	}

	function runValidationNow() {
		validationDebouncedCode = validateAgentWorkflow(buildWf());
	}

	function scheduleValidationDebounced() {
		clearTimeout(validationTimer);
		validationTimer = setTimeout(() => {
			runValidationNow();
			if (browser) saveLocal();
		}, 420);
	}

	function bumpStructural() {
		clearTimeout(validationTimer);
		runValidationNow();
		if (browser) saveLocal();
	}

	function toWorkflowJson(): AgentWorkflowV1 {
		return buildWf();
	}

	function fromWorkflowJson(wf: AgentWorkflowV1, opts?: { recordHistory?: boolean }) {
		if (opts?.recordHistory) pushUndoSnapshot();
		const migrated = normalizeWorkflowForLoad(wf, firstModelId());
		const sid = migrated.startNodeId;
		startNodeId.set(sid);
		nodes.set(migrated.nodes.map((n) => jsonToFlowNode(n, firstModelId())));
		edges.set(
			migrated.edges.map((e) => {
				const when = e.when && e.when !== 'always' ? e.when : undefined;
				const edgeData: Record<string, unknown> = {};
				if (e.disabled) edgeData.disabled = true;
				if (when) edgeData.when = when;
				return {
					id: e.id,
					source: e.fromNodeId,
					target: e.toNodeId,
					...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
					type: 'workflow',
					animated: true,
					...(Object.keys(edgeData).length ? { data: edgeData } : {})
				};
			})
		);
		bumpStructural();
	}

	function saveLocal() {
		try {
			localStorage.setItem(storageKey, JSON.stringify(toWorkflowJson()));
			touchWorkflowUpdated(workflowId);
		} catch {
			// ignore
		}
	}

	function loadLocal() {
		try {
			const raw = localStorage.getItem(storageKey);
			if (!raw) return;
			const wf = JSON.parse(raw) as AgentWorkflowV1;
			if (wf != null && Array.isArray(wf.nodes)) fromWorkflowJson(wf);
		} catch {
			// ignore
		}
	}

	function exportFile() {
		const blob = new Blob([JSON.stringify(toWorkflowJson(), null, 2)], {
			type: 'application/json'
		});
		const a = document.createElement('a');
		a.href = URL.createObjectURL(blob);
		a.download = 'agent-workflow.json';
		a.click();
		URL.revokeObjectURL(a.href);
	}

	function importFile(ev: Event) {
		const input = ev.target as HTMLInputElement;
		const file = input.files?.[0];
		if (!file) return;
		const reader = new FileReader();
		reader.onload = () => {
			try {
				const wf = JSON.parse(String(reader.result)) as AgentWorkflowV1;
				if (wf != null && Array.isArray(wf.nodes)) fromWorkflowJson(wf, { recordHistory: true });
				saveLocal();
			} catch {
				// ignore
			}
			input.value = '';
		};
		reader.readAsText(file);
	}

	$: selectedNodeCount = $nodes.filter((n) => n.selected).length;

	async function handleAiGenerateDraft() {
		const token = browser ? localStorage.token ?? '' : '';
		if (!token) {
			toast.error(get(i18n).t('Not authenticated.'));
			return;
		}
		const mid = effectiveAiModelId;
		if (!mid) {
			toast.error(get(i18n).t('No chat model available. Add a model in settings.'));
			return;
		}
		if (!aiDraftDescription.trim()) {
			toast.error(get(i18n).t('Describe the workflow in the AI draft box first.'));
			return;
		}
		aiBusy = true;
		aiHintsText = '';
		try {
			const r = await generateWorkflowFromDescription(
				token,
				mid,
				aiDraftDescription,
				firstModelId(),
				$models ?? []
			);
			if (!r.ok) {
				toast.error(
					r.error.startsWith('validation:')
						? validationMessage(r.error.replace(/^validation:/, ''), get(i18n).t)
						: r.error
				);
				return;
			}
			fromWorkflowJson(r.workflow, { recordHistory: true });
			saveLocal();
			toast.success(get(i18n).t('Workflow draft applied. Review the canvas and save if needed.'));
		} finally {
			aiBusy = false;
		}
	}

	async function handleAiSuggestFields() {
		const token = browser ? localStorage.token ?? '' : '';
		if (!token) {
			toast.error(get(i18n).t('Not authenticated.'));
			return;
		}
		const mid = effectiveAiModelId;
		if (!mid) {
			toast.error(get(i18n).t('No chat model available. Add a model in settings.'));
			return;
		}
		const sel = get(nodes).filter((n) => n.selected);
		if (sel.length !== 1) {
			toast.error(get(i18n).t('Select exactly one node on the canvas for field hints.'));
			return;
		}
		const n = sel[0];
		aiBusy = true;
		try {
			const r = await suggestNodeFieldsFromContext(token, mid, toWorkflowJson(), {
				id: n.id,
				type: String(n.type ?? ''),
				data: (n.data ?? {}) as Record<string, unknown>,
				position: n.position
			});
			if (!r.ok) {
				toast.error(r.error);
				aiHintsText = '';
				return;
			}
			aiHintsText = r.text;
			toast.success(get(i18n).t('Suggestions generated. See below.'));
		} finally {
			aiBusy = false;
		}
	}

	function validationMessage(code: string, t: (key: string) => string): string {
		const map: Record<string, string> = {
			add_at_least_one_node: t('Add at least one node to run the workflow.'),
			invalid_start_node: t('Select a valid start node.'),
			node_missing_agent: t('Each node must be configured correctly.'),
			agent_missing_model: t('Every node must have a model selected.'),
			start_has_incoming: t('The start node cannot have incoming edges.'),
			unreachable_nodes: t('All nodes must be reachable from the start node.'),
			start_not_source: t('The start node must be a source (no incoming edges).'),
			cycle: t('The workflow graph cannot contain a cycle.'),
			multiple_incoming_not_supported: t(
				'Multiple incoming wires to one block are not supported — use a Merge block.'
			),
			merge_needs_two_inputs: t('Merge needs at least two incoming wires.'),
			merge_edges_must_be_always: t('Merge inputs must use the default edge type (always).'),
			merge_too_many_outgoing: t('Merge can have at most one outgoing wire.'),
			group_has_incoming: t('Group frames cannot have incoming wires.'),
			group_has_outgoing: t('Group frames cannot have outgoing wires.'),
			group_has_edge: t('Wires cannot connect to a Group frame.'),
			if_too_many_outgoing: t('IF can have at most two outgoing wires (true / false).')
		};
		return map[code] ?? code;
	}

	function handleConnect(connection: Connection) {
		pushUndoSnapshot();
		edges.update((eds) =>
			addEdge(
				{
					...connection,
					type: 'workflow',
					animated: true
				},
				eds
			)
		);
		bumpStructural();
	}

	function handleFlowDelete({
		nodes: deletedNodes
	}: {
		nodes: import('@xyflow/svelte').Node[];
		edges: import('@xyflow/svelte').Edge[];
	}) {
		const ids = new Set(deletedNodes.map((n) => n.id));
		const start = get(startNodeId);
		if (start && ids.has(start)) {
			const remaining = get(nodes).filter((n) => !ids.has(n.id));
			startNodeId.set(remaining[0]?.id ?? '');
		}
		bumpStructural();
	}

	$: ($nodes, $edges, $startNodeId, scheduleValidationDebounced());

	$: canRun =
		browser &&
		!running &&
		validationDebouncedCode === null &&
		typeof localStorage !== 'undefined' &&
		!!localStorage.token;

	function handleBeforeDelete({
		nodes: delNodes,
		edges: delEdges
	}: {
		nodes: import('@xyflow/svelte').Node[];
		edges: import('@xyflow/svelte').Edge[];
	}) {
		if (delNodes.length === 0 && delEdges.length === 0) return true;
		pushUndoSnapshot();
		return true;
	}

	async function handleRun() {
		runError = null;
		running = true;
		lastRun = null;
		if (runHighlightTimer != null) {
			clearInterval(runHighlightTimer);
			runHighlightTimer = null;
		}
		runStepHighlightId.set(null);
		try {
			const wf = toWorkflowJson();
			const err = validateAgentWorkflow(wf);
			if (err) {
				const msg = validationMessage(err, get(i18n).t);
				runError = msg;
				toast.error(msg);
				return;
			}
			const token = localStorage.token ?? '';
			if (!token) {
				const msg = get(i18n).t('Not authenticated.');
				runError = msg;
				toast.error(msg);
				return;
			}
			const nList = get(nodes);
			const payloadAgents = nList
				.filter((n) => n.type === 'agent')
				.map((n) => {
					const d = n.data as {
						agentName?: string;
						modelId?: string;
					};
					const name = (d.agentName || '').trim() || `Agent ${n.id.slice(0, 8)}`;
					return {
						id: n.id,
						name,
						modelId: (d.modelId || '').trim()
					};
				});
			const res = await runAgentWorkflow(token, {
				user_input: userInput,
				workflow: wf as unknown as Record<string, unknown>,
				agents: payloadAgents,
				image_prompt_refine_model: firstModelId() || undefined
			});
			lastRun = res;
			const order =
				res.order?.length > 0 ? res.order : res.logs.map((l) => l.nodeId);
			if (order.length === 0) {
				runStepHighlightId.set(null);
			} else {
				let step = 0;
				runStepHighlightId.set(order[0] ?? null);
				runHighlightTimer = setInterval(() => {
					step += 1;
					if (step >= order.length) {
						if (runHighlightTimer != null) clearInterval(runHighlightTimer);
						runHighlightTimer = null;
						runStepHighlightId.set(null);
						return;
					}
					runStepHighlightId.set(order[step] ?? null);
				}, 480);
			}
			toast.success(get(i18n).t('Workflow finished.'));
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			runError = msg;
			toast.error(msg);
		} finally {
			running = false;
		}
	}

	onMount(() => {
		if (!browser) return;
		const raw = localStorage.getItem(workflowStorageKey(workflowId));
		const ent = getWorkflowEntry(workflowId);
		if (!raw && !ent) {
			goto('/agent-workflow');
			return;
		}
		if (raw && !ent) {
			ensureWorkflowInIndex(workflowId, get(i18n).t('Untitled'));
		}
		loadLocal();
		if (get(nodes).length === 0) {
			addNodeAt('trigger', { x: 120, y: 100 }, firstModelId());
			bumpStructural();
		} else {
			runValidationNow();
		}
		clearWorkflowHistory();
	});

	$: colorMode = (
		$theme.includes('dark')
			? 'dark'
			: $theme === 'system' && typeof window !== 'undefined'
				? window.matchMedia('(prefers-color-scheme: dark)').matches
					? 'dark'
					: 'light'
				: 'light'
	) as ColorMode;
</script>

<SvelteFlowProvider>
	<div class="flex flex-col h-full min-h-0 w-full">
		<div
			class="flex flex-wrap items-center gap-2 px-3 py-2 border-b border-gray-100 dark:border-gray-800 shrink-0"
		>
			<div class="flex flex-wrap gap-1 items-center">
				<span class="text-xs text-gray-500 mr-1">{$i18n.t('Add block')}:</span>
				{#each Object.keys(NODE_REGISTRY) as ft (ft)}
					<button
						type="button"
						class="px-2 py-1 text-xs rounded-lg bg-gray-100 dark:bg-gray-800 hover:bg-gray-200 dark:hover:bg-gray-700 inline-flex items-center gap-1"
						title={NODE_REGISTRY[ft as FlowNodeTypeId].category ?? ''}
						on:click={() => canvasExtras?.quickAddAtCenter(ft as FlowNodeTypeId)}
					>
						{#if NODE_REGISTRY[ft as FlowNodeTypeId].icon}
							<span aria-hidden="true">{NODE_REGISTRY[ft as FlowNodeTypeId].icon}</span>
						{/if}
						{$i18n.t(NODE_REGISTRY[ft as FlowNodeTypeId].labelKey)}
					</button>
				{/each}
				<button
					type="button"
					class="px-2 py-1 text-xs rounded-lg border border-dashed border-gray-300 dark:border-gray-600 text-gray-600 dark:text-gray-400"
					on:click={() => canvasExtras?.openPickerCenter()}
				>
					{$i18n.t('More')}
				</button>
			</div>
			<button
				type="button"
				class="px-3 py-1.5 text-sm rounded-lg bg-gray-100 dark:bg-gray-800"
				on:click={exportFile}
			>
				{$i18n.t('Export JSON')}
			</button>
			<label
				class="px-3 py-1.5 text-sm rounded-lg bg-gray-100 dark:bg-gray-800 cursor-pointer"
			>
				{$i18n.t('Import JSON')}
				<input type="file" accept="application/json,.json" class="hidden" on:change={importFile} />
			</label>
			<button
				type="button"
				class="px-3 py-1.5 text-sm rounded-lg {canRun
					? 'bg-emerald-600 text-white'
					: 'bg-gray-200 dark:bg-gray-700 text-gray-500 cursor-not-allowed'}"
				disabled={!canRun}
				on:click={handleRun}
			>
				{running ? $i18n.t('Running…') : $i18n.t('Run workflow')}
			</button>
		</div>

		<div class="flex flex-1 min-h-0 w-full">
			<div class="flex-1 min-h-[320px] min-w-0 relative">
				<SvelteFlow
					{nodes}
					{edges}
					{nodeTypes}
					{edgeTypes}
					defaultEdgeOptions={{ type: 'workflow', animated: true, interactionWidth: 28 }}
					minZoom={0.1}
					maxZoom={2}
					{colorMode}
					snapGrid={[16, 16]}
					nodesDraggable={true}
					nodesConnectable={true}
					elementsSelectable={true}
					deleteKey={['Delete', 'Backspace']}
					panOnScroll={true}
					panOnDrag={true}
					selectionOnDrag={false}
					isValidConnection={isValidWorkflowConnection}
					onconnect={handleConnect}
					onconnectend={(ev, st) => get(connectEndBridge)?.(ev, st)}
					onbeforedelete={handleBeforeDelete}
					ondelete={handleFlowDelete}
				>
					<FlowCanvasExtras
						bind:this={canvasExtras}
						onStructureChange={bumpStructural}
						defaultModelId={firstModelId()}
					/>
					<Background variant={BackgroundVariant.Dots} />
				</SvelteFlow>
			</div>

			<aside
				class="w-[min(100%,22rem)] shrink-0 border-l border-gray-100 dark:border-gray-800 flex flex-col bg-white dark:bg-gray-950"
			>
				<div class="p-3 border-b border-gray-100 dark:border-gray-800">
					<label class="block text-xs font-medium text-gray-700 dark:text-gray-300">
						{$i18n.t('Initial user message')}
						<textarea
							class="mt-1 w-full text-sm rounded-lg border border-gray-200 dark:border-gray-700 px-2 py-1.5 min-h-[88px] bg-gray-50 dark:bg-gray-900"
							placeholder={$i18n.t('Describe what you want the workflow to do…')}
							bind:value={userInput}
							disabled={running}
						></textarea>
					</label>
					{#if validationDebouncedCode}
						<p class="mt-2 text-xs text-amber-700 dark:text-amber-400">
							{validationMessage(validationDebouncedCode, $i18n.t)}
						</p>
					{/if}
					{#if runError}
						<p class="mt-2 text-xs text-red-600 dark:text-red-400">{runError}</p>
					{/if}
				</div>
				<div
					class="p-3 border-b border-gray-100 dark:border-gray-800 space-y-2 bg-violet-50/40 dark:bg-violet-950/20"
				>
					<div class="text-xs font-semibold text-gray-800 dark:text-gray-100">
						{$i18n.t('AI workflow draft')}
					</div>
					<p class="text-[10px] text-gray-600 dark:text-gray-400 leading-snug">
						{$i18n.t(
							'Describe steps and branches in plain language. The graph will be replaced — use undo if needed.'
						)}
					</p>
					<p class="text-[10px] text-gray-700 dark:text-gray-300 leading-snug">
						<span class="font-medium text-gray-800 dark:text-gray-100"
							>{$i18n.t('Draft model')}:</span
						>
						<span class="ml-1">{modelLabel($models ?? [], effectiveAiModelId)}</span>
						{#if !aiModelManual}
							<span class="ml-1 text-emerald-700 dark:text-emerald-400"
								>({$i18n.t('automatic — text / JSON')})</span
							>
						{/if}
					</p>
					<details class="text-[10px] text-gray-600 dark:text-gray-400">
						<summary class="cursor-pointer text-violet-700 dark:text-violet-300 select-none">
							{$i18n.t('Override model')}
						</summary>
						<select
							class="mt-1 w-full text-xs rounded-lg border border-gray-200 dark:border-gray-700 px-2 py-1.5 bg-white dark:bg-gray-900"
							bind:value={aiModelManual}
							disabled={aiBusy}
						>
							<option value="">{$i18n.t('Automatic (recommended)')}</option>
							{#each $models ?? [] as m (m.id)}
								<option value={m.id}>{m.name ?? m.id}</option>
							{/each}
						</select>
					</details>
					<textarea
						class="w-full text-xs rounded-lg border border-gray-200 dark:border-gray-700 px-2 py-1.5 min-h-[72px] bg-white dark:bg-gray-900"
						placeholder={$i18n.t('e.g. Trigger, then IF user input equals 1, call agent A else agent B…')}
						bind:value={aiDraftDescription}
						disabled={aiBusy}
					></textarea>
					<div class="flex flex-wrap gap-2">
						<button
							type="button"
							class="px-2 py-1 text-[11px] rounded-lg bg-violet-600 text-white disabled:opacity-50"
							disabled={aiBusy || !($models ?? []).length}
							on:click={handleAiGenerateDraft}
						>
							{aiBusy ? $i18n.t('Running…') : $i18n.t('Generate graph')}
						</button>
						<button
							type="button"
							class="px-2 py-1 text-[11px] rounded-lg border border-violet-300 dark:border-violet-700 text-violet-800 dark:text-violet-200 disabled:opacity-50"
							disabled={aiBusy || selectedNodeCount !== 1 || !($models ?? []).length}
							on:click={handleAiSuggestFields}
							title={$i18n.t('Select one node')}
						>
							{$i18n.t('Suggest fields')}
						</button>
					</div>
					{#if aiHintsText}
						<pre
							class="text-[10px] whitespace-pre-wrap text-gray-800 dark:text-gray-200 bg-white/80 dark:bg-gray-900/80 rounded-lg p-2 border border-violet-100 dark:border-violet-900 max-h-40 overflow-y-auto"
						>{aiHintsText}</pre>
					{/if}
				</div>
				<div class="flex-1 min-h-0 overflow-y-auto p-3 space-y-3">
					{#if lastRun}
						<div>
							<div class="text-xs font-semibold text-gray-700 dark:text-gray-200 mb-1">
								{$i18n.t('Final result')}
							</div>
							<div
								class="text-xs text-gray-800 dark:text-gray-100 bg-gray-50 dark:bg-gray-900 rounded-lg p-2 border border-gray-100 dark:border-gray-800 prose dark:prose-invert max-w-none prose-img:rounded-lg prose-img:max-w-full"
							>
								{@html DOMPurify.sanitize(
									marked.parse(lastRun.final || '', { async: false }) as string
								)}
							</div>
						</div>
						<details class="text-xs">
							<summary class="cursor-pointer font-medium text-gray-700 dark:text-gray-200">
								{$i18n.t('Per-node logs')}
							</summary>
							<ul class="mt-2 space-y-2">
								{#each lastRun.logs as log (log.nodeId)}
									<li class="border border-gray-100 dark:border-gray-800 rounded-lg p-2 space-y-1">
										<div class="font-mono text-[10px] text-gray-500">
											{log.nodeId}
											{#if log.mode === 'image'}
												<span class="text-violet-600 dark:text-violet-400"> · image</span>
											{/if}
										</div>
										{#if log.mode === 'image' && log.imagePrompt != null}
											<div class="text-[10px] text-gray-500">
												<span class="font-medium">{$i18n.t('Image prompt used')}:</span>
												{log.imagePrompt}
											</div>
										{/if}
										{#if log.mode === 'image' && log.imageUrls?.length}
											<div class="flex flex-wrap gap-1 mt-1">
												{#each log.imageUrls as u (u)}
													<img
														src={u}
														alt=""
														class="max-h-24 rounded border border-gray-200 dark:border-gray-700 object-contain"
													/>
												{/each}
											</div>
										{/if}
										<div class="text-gray-600 dark:text-gray-400">{log.outputPreview}</div>
									</li>
								{/each}
							</ul>
						</details>
					{:else}
						<p class="text-xs text-gray-500">
							{$i18n.t('Run results will appear here after you press Run workflow.')}
						</p>
					{/if}
				</div>
			</aside>
		</div>

		<p class="text-xs text-gray-500 dark:text-gray-400 px-3 py-2 border-t border-gray-100 dark:border-gray-800">
			{$i18n.t(
				'Blocks run from the Start node. IF uses two outputs (true/false). Use a Merge block for multiple inputs. Double-click or Shift+click empty canvas to add a node. To remove a connection, click the wire (it highlights), then press Delete or Backspace, or use the trash control on the canvas.'
			)}
		</p>
	</div>

	<NodePicker defaultModelId={firstModelId()} onPicked={bumpStructural} />
</SvelteFlowProvider>

<style>
	/* Group: один визуальный слой — убираем дефолтный «коробочный» фон/тень обёртки xyflow */
	:global(.svelte-flow__node.agent-workflow-group-node) {
		background: transparent !important;
		border: none !important;
		box-shadow: none !important;
		padding: 0 !important;
	}
</style>
