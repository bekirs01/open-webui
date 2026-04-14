import type { Edge } from '@xyflow/svelte';

export function prettyWireJson(raw: string | null | undefined): string {
	if (raw == null || raw === '') return '';
	try {
		return JSON.stringify(JSON.parse(raw), null, 2);
	} catch {
		return String(raw);
	}
}

/** First wire item's `json` object (expression `$json` in backend). */
export function getWireFirstItemJson(
	wireText: string | null | undefined
): Record<string, unknown> | null {
	if (wireText == null || wireText === '') return null;
	try {
		const o = JSON.parse(wireText) as { items?: Array<{ json?: unknown }> };
		const j = o?.items?.[0]?.json;
		if (j && typeof j === 'object' && !Array.isArray(j)) return j as Record<string, unknown>;
		return null;
	} catch {
		return null;
	}
}

export function getIncomingSources(nodeId: string, edges: Edge[]): string[] {
	return edges.filter((e) => e.target === nodeId).map((e) => e.source);
}

export function resolveInputWireText(opts: {
	nodeId: string;
	nodeType: string | undefined;
	edges: Edge[];
	results: Record<string, string> | undefined;
	userInput: string;
}): string {
	const { nodeId, nodeType, edges, results, userInput } = opts;
	const parents = getIncomingSources(nodeId, edges);
	if (parents.length === 0) {
		if (nodeType === 'trigger') {
			return JSON.stringify(
				{ userInput: userInput || '', _note: 'Initial message from Run panel (preview)' },
				null,
				2
			);
		}
		return '';
	}
	if (parents.length === 1) {
		const w = results?.[parents[0]];
		return w != null && w !== '' ? prettyWireJson(w) : '';
	}
	return parents
		.map((pid) => {
			const w = results?.[pid];
			const head = `/* ← ${pid.slice(0, 10)}… */\n`;
			return head + (w != null && w !== '' ? prettyWireJson(w) : '—');
		})
		.join('\n\n');
}

export function resolveOutputWireText(
	nodeId: string,
	results: Record<string, string> | undefined
): string {
	const w = results?.[nodeId];
	if (w == null || w === '') return '';
	return prettyWireJson(w);
}
