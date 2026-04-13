<script lang="ts">
	import { getContext } from 'svelte';
	import type { Writable } from 'svelte/store';
	import type { i18n as I18nInstance } from 'i18next';
	import { WEBUI_NAME } from '$lib/stores';

	const i18n = getContext<Writable<I18nInstance>>('i18n');
</script>

<svelte:head>
	<title>{$i18n.t('Agent workflows')} • {$WEBUI_NAME}</title>
</svelte:head>

<slot />
