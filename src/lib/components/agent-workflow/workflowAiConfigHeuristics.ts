/**
 * Fills missing if_else / transform config from the user's natural-language description
 * when the model left fields empty or at defaults. Keeps structure/edges unchanged.
 */

import type { AgentWorkflowV1, WorkflowNodeKind } from './types';

function nk(n: { nodeType?: WorkflowNodeKind }): WorkflowNodeKind {
	return n.nodeType ?? 'agent';
}

/** Double/single/angle quotes — common in RU/EN prompts. */
export function extractQuotedStrings(description: string): string[] {
	const out: string[] = [];
	const re = /"([^"\\]*)"|«([^»]*)»|'([^']{2,})'/gu;
	let m: RegExpExecArray | null;
	while ((m = re.exec(description)) !== null) {
		const t = (m[1] ?? m[2] ?? m[3] ?? '').trim();
		if (t.length >= 2 && t.length < 800) out.push(t);
	}
	return out;
}

/**
 * Best-effort: substring token for IF (e.g. refund) from mixed RU/EN text.
 */
export function extractSubstringSearchToken(description: string): string | null {
	const d = description.trim();
	if (!d) return null;

	const patterns: RegExp[] = [
		/(?:подстрока|substring|sub-?string)[^"'\n«]{0,120}["«]([^"»]{1,64})["»]/iu,
		/(?:подстрока|substring)[^"'\n]{0,120}["']([a-zA-Zа-яА-Я0-9_-]{1,48})["']/iu,
		/(?:contains|в тексте есть|есть в тексте)[^"'\n]{0,80}["«']([a-zA-Zа-яА-Я0-9_-]{1,48})["'»]/iu,
	];

	for (const re of patterns) {
		const m = d.match(re);
		if (m?.[1]?.trim()) return m[1].trim();
	}

	if (/\brefund\b/i.test(d) && /(?:подстрок|substring|IF|Узел\s+IF)/i.test(d)) {
		return 'refund';
	}

	const oneWordQuotes = extractQuotedStrings(d).filter((q) => !/\s/.test(q) && q.length <= 48);
	if (oneWordQuotes.length === 1) return oneWordQuotes[0];

	return null;
}

function needsTemplateFill(template: unknown): boolean {
	const s = String(template ?? '').trim();
	return !s || s === '{{input}}';
}

function normHandle(h: string | undefined): string {
	return (h ?? '').toLowerCase();
}

/**
 * Deep-clone nodes and fill missing config.condition / config.template when possible.
 */
export function enrichWorkflowConfigFromUserDescription(
	description: string,
	wf: AgentWorkflowV1
): AgentWorkflowV1 {
	const desc = description.trim();
	if (!desc) return wf;

	const substringToken = extractSubstringSearchToken(desc);
	const allQuotes = extractQuotedStrings(desc);
	const templateQuotes = substringToken
		? allQuotes.filter((q) => q !== substringToken)
		: [...allQuotes];

	const nodes = wf.nodes.map((n) => ({
		...n,
		config: n.config ? { ...n.config } : {}
	}));

	const ifNodes = nodes.filter((n) => nk(n) === 'if_else');
	for (const n of ifNodes) {
		const cfg = n.config as Record<string, unknown>;
		const expr = String(cfg.conditionExpression ?? '').trim();
		if (expr) continue;

		const mode = String(cfg.conditionMode ?? 'substring').toLowerCase();
		if (mode !== 'substring' && mode !== '') continue;

		const cond = String(cfg.condition ?? '').trim();
		if (cond) continue;

		if (substringToken) {
			cfg.conditionMode = 'substring';
			cfg.condition = substringToken;
			if (cfg.conditionExpression === undefined) cfg.conditionExpression = '';
		}
	}

	const transforms = nodes.filter((n) => nk(n) === 'transform');
	if (transforms.length === 0 || templateQuotes.length === 0) {
		return { ...wf, nodes };
	}

	const ifNode = ifNodes[0];
	let trueId: string | undefined;
	let falseId: string | undefined;
	if (ifNode) {
		for (const e of wf.edges) {
			if (e.fromNodeId !== ifNode.id) continue;
			const h = normHandle(e.sourceHandle);
			if (h === 'true') trueId = e.toNodeId;
			if (h === 'false') falseId = e.toNodeId;
		}
	}

	const applyTemplate = (nodeId: string, text: string) => {
		const n = nodes.find((x) => x.id === nodeId);
		if (!n || nk(n) !== 'transform') return;
		const cfg = n.config as Record<string, unknown>;
		if (!needsTemplateFill(cfg.template)) return;
		cfg.template = text;
	};

	if (
		transforms.length === 2 &&
		templateQuotes.length >= 2 &&
		trueId &&
		falseId &&
		templateQuotes[0] !== undefined &&
		templateQuotes[1] !== undefined
	) {
		applyTemplate(trueId, templateQuotes[0]);
		applyTemplate(falseId, templateQuotes[1]);
	} else {
		const sorted = [...transforms].sort(
			(a, b) => (a.position?.y ?? 0) - (b.position?.y ?? 0) || (a.position?.x ?? 0) - (b.position?.x ?? 0)
		);
		for (let i = 0; i < sorted.length && i < templateQuotes.length; i++) {
			const cfg = sorted[i].config as Record<string, unknown>;
			if (!needsTemplateFill(cfg.template)) continue;
			cfg.template = templateQuotes[i];
		}
	}

	return { ...wf, nodes };
}
