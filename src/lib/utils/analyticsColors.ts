/**
 * Shared palette for admin analytics (line chart, usage bar, tooltips).
 * Same model_id always maps to the same color via colorForModelId().
 */
export const ANALYTICS_MODEL_PALETTE: string[] = [
	'#3b82f6',
	'#10b981',
	'#f59e0b',
	'#ef4444',
	'#8b5cf6',
	'#ec4899',
	'#06b6d4',
	'#84cc16',
	'#f97316',
	'#6366f1',
	'#14b8a6',
	'#eab308',
	'#dc2626'
];

/** Stable index from string (FNV-1a style mix). */
function hashModelId(modelId: string): number {
	let h = 2166136261;
	for (let i = 0; i < modelId.length; i++) {
		h ^= modelId.charCodeAt(i);
		h = Math.imul(h, 16777619);
	}
	return Math.abs(h);
}

export function colorForModelId(
	modelId: string,
	palette: readonly string[] = ANALYTICS_MODEL_PALETTE
): string {
	if (!modelId || palette.length === 0) return '#94a3b8';
	return palette[hashModelId(modelId) % palette.length];
}
