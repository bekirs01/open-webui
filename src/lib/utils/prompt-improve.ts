import type { Model } from '$lib/stores';

/**
 * System prompt for "Improve prompt": optimizer instructions + same-language + no leaked tags.
 */
export const PROMPT_IMPROVE_SYSTEM = `META-TASK — YOU REWRITE PROMPTS ONLY, YOU DO NOT ANSWER THEM:
- Your output must be **only** a clearer **instruction / prompt** for a *different* model to execute later. You **never** produce the finished answer, essay, report, or explanation that the user would want as a result.
- If the user wrote a question (e.g. «Расскажи про Америку» / «Tell me about X»), you must output a **better formulation of that request** (scope, angle, format, depth, language) — **not** the actual content about America or X.
- Keep length **moderate**: usually a few sentences or one short paragraph of improved instruction — **not** a long article and not a full outline of the answer. Add specificity so the next model understands the task; do not perform the task yourself.

You improve prompts for downstream AI (images, text, etc.). The user must get a clearly better instruction, but the **same concrete request** — never a different scene or missing subjects.

NON-NEGOTIABLE — preserve meaning and entities:
- Repeat **every** person, animal, object, place, and proper name from the user using the **same words** (same spelling/script) on at least one clear mention. Never delete or replace a named person with a generic label ("политик", "всадник", "figure", "rider", "man", "subject") or drop them to focus on something else.
- If the user asked for "A on B" (e.g. Trump on a horse), the improved prompt must still be **about A and B together**, not only a beautiful B or only a generic rider.
- You may add helpful detail (pose, framing, lighting, style level, clarity) **in addition** to naming everything — not **instead** of it. Prefer opening with one sentence that states the full request with all key subjects.

How to improve (do this):
- Make the task unambiguous: better verbs, order, and concrete wording so models follow the intent.
- For image/video: you may add short, generic execution hints (composition, atmosphere, quality) that do **not** introduce new characters or replace the user's subjects.
- Remove only meaningless filler ("ну", "типа", "just", "simply") if it adds nothing.

Do NOT:
- Invent new people, objects, colors, brands, or plot that the user did not mention.
- Output only a generic scene description when the user named specific subjects.
- Output commentary, titles, or quotation marks around the whole prompt.

Language: match the user's language; keep proper names exactly as they wrote them. No mixing in foreign words unless the user did.

Before you answer, verify every important word from the user about **who/what** appears in your text. If not, rewrite until they do.

Output only the final improved prompt as plain text. No XML, no code fences, no thinking tags.`;

/** Reasoning / chain-of-thought models: very slow for this subtask and often answer instead of rewriting. */
export function isReasoningOrSlowPromptImproveModel(modelId: string, modelName: string): boolean {
	const s = `${modelId} ${modelName ?? ''}`.toLowerCase();
	return (
		/\br1\b|deepseek-r1|r1-distill|distill-r1|qwq|qw[-_]?q|reasoning|sonar-reasoning|-thinking\b|o1-preview|o1-mini|^o1$|o3-mini|o4-mini/.test(s) ||
		/claude.*opus|gemini.*ultra|qwen.*110b|llama.*405/.test(s)
	);
}

/**
 * Pick a fast instruct model for prompt rewriting — avoid reasoning models (R1, QwQ, o-series, etc.).
 */
export function pickPromptImproveModel(models: Model[], selectedIds: string[]): string | null {
	if (!models?.length) return null;

	const eligible = models.filter((m) => !isReasoningOrSlowPromptImproveModel(m.id, m.name ?? ''));
	const pool = eligible.length ? eligible : models;

	const scoreModel = (m: Model): number => {
		const id = `${m.id}`.toLowerCase();
		const name = `${m.name ?? ''}`.toLowerCase();
		const s = `${id} ${name}`;
		let sc = 0;
		if (/4o-mini|gpt-4o-mini|gpt-4\.1-mini|mini|flash|flash-lite|instant|turbo|haiku|3\.5|gpt-3\.5|8b-instruct|7b-instruct/.test(s)) sc += 100;
		if (/\bgpt[-_]?5|gpt[-_]?4\.?5|gpt[-_]?4o|gpt[-_]?4\b/.test(s) && !/mini|flash/.test(s)) sc += 70;
		if (/claude.*(sonnet|3\.5|3-5)/.test(s)) sc += 68;
		if (/gemini.*(2\.|pro|flash)/.test(s) && !/ultra/.test(s)) sc += 65;
		if (/deepseek/i.test(s) && !/r1|distill-r1/.test(s) && /v3|chat/.test(s)) sc += 55;
		if (/qwen(?!.*qwq)/.test(s) && /(7b|14b|32b)/.test(s)) sc += 50;
		if (/llama.*(8b|70b)(?!.*405)/.test(s)) sc += 45;
		if (/mistral|mixtral|command-r/.test(s)) sc += 40;
		if (/\b(405|235b)\b/.test(s)) sc -= 15;
		if (selectedIds?.includes(m.id)) sc += 15;
		return sc;
	};

	let best = pool[0];
	let bestScore = scoreModel(best);
	for (let i = 1; i < pool.length; i++) {
		const sc = scoreModel(pool[i]);
		if (sc > bestScore) {
			bestScore = sc;
			best = pool[i];
		}
	}
	return best?.id ?? null;
}

/** Same fast-model heuristic as prompt improve — use for voice-call LLM when the selected model is slow. */
export function pickVoiceChatModel(models: Model[], selectedIds: string[]): string | null {
	return pickPromptImproveModel(models, selectedIds);
}

export function normalizePromptForCompare(a: string, b: string): boolean {
	return (
		a.trim().replace(/\s+/g, ' ') ===
		b.trim().replace(/\s+/g, ' ')
	);
}

/** At least this many whitespace-separated tokens (words) required to run Improve prompt. */
export function hasMinWordCountForPromptImprove(text: string, minWords = 2): boolean {
	const parts = (text ?? '').trim().split(/\s+/).filter((w) => w.length > 0);
	return parts.length >= minWords;
}

/** Remove leaked reasoning / XML-style blocks some models still emit. */
export function stripPromptImproveArtifacts(text: string): string {
	let s = text;
	s = s.replace(/<redacted_thinking>[\s\S]*?<\/redacted_thinking>/gi, '');
	s = s.replace(/<think\b[\s\S]*?<\/think>/gi, '');
	s = s.replace(/<think\b[\s\S]*$/gi, '');
	return s.trim();
}

/**
 * Drop characters from scripts the user did not use in their draft (fixes EN/CJK leaking into RU, etc.).
 * Counts letter-like characters per script; strips whole scripts only when absent from draft.
 */
export function enforceDraftScriptLanguage(draft: string, improved: string): string {
	const cyr = (draft.match(/[\u0400-\u04FF]/g) || []).length;
	const lat = (draft.match(/[A-Za-z]/g) || []).length;
	const cjk = (draft.match(/[\u3000-\u9FFF\uAC00-\uD7AF\uFF00-\uFFEF]/g) || []).length;

	let out = improved;

	if (cjk === 0) {
		out = out.replace(/[\u3000-\u9FFF\uAC00-\uD7AF\uFF00-\uFFEF]/g, '');
	}
	if (lat === 0) {
		out = out.replace(/[A-Za-z]+/g, ' ');
	}
	if (cyr === 0) {
		out = out.replace(/[\u0400-\u04FF]+/g, ' ');
	}

	out = out.replace(/_+/g, ' ').replace(/\s+/g, ' ').trim();

	return out;
}
