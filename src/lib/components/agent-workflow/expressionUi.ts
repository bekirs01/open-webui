/**
 * Helpers for n8n-style workflow expressions in the UI ({{$json.x}}, ={{...}}).
 * Must stay aligned with backend `workflow_expr.py` (allowed field paths).
 */

/** Typical keys on trigger / agent wire item json — quick presets in the editor. */
export const COMMON_JSON_FIELD_PRESETS = [
	{ key: 'userInput', labelKey: 'User input (trigger)' },
	{ key: 'status', labelKey: 'Status (trigger)' },
	{ key: 'reply', labelKey: 'Reply (agent text)' }
] as const;

/** Allow dotted paths: age, user.name */
export function sanitizeJsonFieldPath(raw: string): string {
	return raw.replace(/[^a-zA-Z0-9_.]/g, '').slice(0, 160);
}

export function templateJsonField(field: string): string {
	const f = sanitizeJsonFieldPath(field);
	return f ? `{{$json.${f}}}` : '';
}

export function formulaJsonField(field: string): string {
	const f = sanitizeJsonFieldPath(field);
	return f ? `={{$json.${f}}}` : '';
}

const CMP_OPS = ['>', '>=', '<', '<=', '==', '!='] as const;

export function buildComparisonFormula(
	field: string,
	op: (typeof CMP_OPS)[number],
	valueRaw: string
): string {
	const f = sanitizeJsonFieldPath(field);
	if (!f) return '';
	const v = valueRaw.trim();
	if (v === '') return `={{$json.${f} ${op} }}`;
	const asNum = Number(v);
	if (Number.isFinite(asNum) && String(asNum) === v) {
		return `={{$json.${f} ${op} ${asNum}}}`;
	}
	const esc = JSON.stringify(v);
	return `={{$json.${f} ${op} ${esc}}}`;
}

export { CMP_OPS };

/** Insert `snippet` into `current` at caret (for template / expression fields). */
export function insertAtCaret(
	current: string,
	selectionStart: number | null | undefined,
	selectionEnd: number | null | undefined,
	snippet: string
): { next: string; caret: number } {
	const len = current.length;
	const s = Math.max(0, Math.min(selectionStart ?? len, len));
	const e = Math.max(s, Math.min(selectionEnd ?? len, len));
	const next = current.slice(0, s) + snippet + current.slice(e);
	return { next, caret: s + snippet.length };
}
