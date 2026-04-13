<script lang="ts">
	import { getContext, onMount } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';
	import { goto } from '$app/navigation';
	import { page } from '$app/stores';
	import { user } from '$lib/stores';

	import AgentWorkflowPageShell from '$lib/components/agent-workflow/AgentWorkflowPageShell.svelte';
	import AgentWorkflowEditor from '$lib/components/agent-workflow/AgentWorkflowEditor.svelte';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	let loaded = false;

	$: id = $page.params.id ?? '';

	onMount(() => {
		if ($user === undefined || $user === null) {
			goto('/auth');
			return;
		}
		if (!id) {
			goto('/agent-workflow');
			return;
		}
		loaded = true;
	});
</script>

{#if loaded && id}
	<AgentWorkflowPageShell title={$i18n.t('Workflow')} showBack={true}>
		<AgentWorkflowEditor workflowId={id} />
	</AgentWorkflowPageShell>
{/if}
