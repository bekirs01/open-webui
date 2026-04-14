<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';
	import { toast } from 'svelte-sonner';

	import { templateJsonField, templateNodeJsonField } from './expressionUi';

	const i18n = getContext<Writable<I18nInstance>>('i18n');

	/** Root of `items[0].json` — same as backend `$json`. */
	export let data: Record<string, unknown> | null;
	/** If set, insert `{{$node["…"].json…}}` instead of `{{$json…}}`. */
	export let nodeExpressionKey: string | null = null;
	export let pathPrefix: string[] = [];

	function dottedPath(keys: string[]): string {
		return keys.join('.');
	}

	function snippet(keys: string[]): string {
		const d = dottedPath(keys);
		return d ? templateJsonField(d) : '';
	}

	function onDragStart(e: DragEvent, keys: string[]) {
		const s = snippet(keys);
		if (!s) return;
		e.dataTransfer?.setData('text/plain', s);
		e.dataTransfer?.setData('application/x-agent-wf-snippet', s);
		e.dataTransfer!.effectAllowed = 'copy';
	}

	function copy(keys: string[]) {
		const s = snippet(keys);
		if (!s) return;
		void navigator.clipboard.writeText(s).then(() => {
			toast.success($i18n.t('Copied') + ': ' + s);
		});
	}
</script>

{#if data && typeof data === 'object'}
	<ul class="text-[10px] font-mono space-y-0.5 pl-1 border-l border-gray-200 dark:border-gray-700">
		{#each Object.entries(data) as [key, val] (pathPrefix.join('.') + key)}
			<li class="pl-1">
				{#if val !== null && typeof val === 'object' && !Array.isArray(val)}
					<div class="text-gray-500 dark:text-gray-400 select-none">{key}</div>
					<svelte:self
						data={val as Record<string, unknown>}
						pathPrefix={[...pathPrefix, key]}
						{nodeExpressionKey}
					/>
				{:else}
					<div class="flex flex-wrap items-center gap-1 group">
						<button
							type="button"
							class="text-left text-sky-700 dark:text-sky-300 hover:underline max-w-[180px] truncate"
							title={nodeExpressionKey
								? $i18n.t('Click to copy {{$node…}}')
								: $i18n.t('Click to copy {{$json…}}')}
							draggable="true"
							on:dragstart={(e) => onDragStart(e, [...pathPrefix, key])}
							on:click|preventDefault={() => copy([...pathPrefix, key])}
						>
							<span class="text-gray-600 dark:text-gray-400">{key}</span>
							<span class="text-gray-400 dark:text-gray-500"> = </span>
							<span class="text-gray-800 dark:text-gray-200"
								>{typeof val === 'string' ? JSON.stringify(val.slice(0, 80)) : JSON.stringify(val)}</span
							>
						</button>
						<span
							class="opacity-0 group-hover:opacity-100 text-[9px] text-gray-400"
							aria-hidden="true"
							>⇄</span
						>
					</div>
				{/if}
			</li>
		{/each}
	</ul>
{:else}
	<p class="text-[10px] text-gray-500">{$i18n.t('No JSON fields (run workflow first).')}</p>
{/if}
