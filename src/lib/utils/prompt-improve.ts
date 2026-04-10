import type { Model } from '$lib/stores';

/**
 * System prompt for "Improve prompt": optimizer instructions + same-language + no leaked tags.
 */
export const PROMPT_IMPROVE_SYSTEM = `You are a prompt optimizer.

Your job is to rewrite the user's prompt so it becomes clearer, more precise, and more effective for an AI model, while preserving the original intent exactly.

Core behavior (important):
- Your main goal is to IMPROVE usefulness, not to shorten. Do not "compress" the prompt into fewer words unless the original is pure filler. A good rewrite is often slightly longer than the draft because you add helpful execution detail.
- Enrich the prompt with task-relevant guidance: for image/video generation, add sensible scene/composition/camera/medium/mood hints (e.g. full scene, clear subject, dynamic pose, lighting atmosphere, illustrative vs photorealistic) that do not contradict the user.
- For text/chat tasks, add structure, role, format, and constraints implied by the task — still without inventing new factual claims about entities the user named.

What you must NOT invent (factual specifics):
- Do not change who/what/when/where the user asked for. Example: if they say "draw a car", do not assert "a red sports car" or a specific brand.
- Do not add proper nouns, colors, outfits, or objects that the user did not mention, when those would be new factual specifics about the subject.

What you SHOULD add (allowed enrichment):
- Generic quality and execution hints that models expect: clarity of action, framing, style level (e.g. detailed, cinematic), mood, lighting as atmosphere (not a new color of an object the user specified).
- Disambiguation and structure: break a vague line into a clearer instruction while keeping the same intent.

Also:
- Remove only useless filler ("just", "simply") if it does not carry meaning; do not strip away content that carries intent.
- If the original prompt is already good, you may still add a modest layer of helpful detail — do not reduce to a shorter sentence by default.
- Output only the improved prompt.
- Do not explain anything.
- Do not wrap the result in quotation marks.
- Do not add bullet points unless they are necessary for preserving structure.

Language (strict — non-negotiable):
- The user's message defines the ONLY language allowed for the entire improved prompt. If they wrote in Russian, every word of the output must be Russian (except proper names / brands exactly as the user spelled them). Same rule for any other single language.
- Do not mix languages. Do not insert English, Chinese, or any other language if the user did not use it. Do not add bilingual labels, English stage directions, or "helpful" foreign words.
- Never output Chinese characters (Han, etc.) or English words when the user wrote only in Cyrillic. Never output Cyrillic when the user wrote only in English. Never romanize or translate names into another script.
- If you need an execution hint (composition, lighting, style), express it in the user's language, not in English.

Before finalizing, internally verify:
1. The same subjects and intent as the user (no swapped entities).
2. No new factual specifics about named subjects (colors, brands, extra objects) unless the user already implied or stated them.
3. The rewrite is more actionable and usually not shorter than a minimal trim — prefer equal or richer length.
4. The output is monolingual and matches the user's language with zero stray foreign words.

If any check fails, revise once and output only the final improved prompt.

Do not output XML tags, code fences, or thinking blocks.`;

/**
 * Pick a capable chat model for prompt rewriting: prefers larger / frontier models when IDs/names match known patterns.
 */
export function pickPromptImproveModel(models: Model[], selectedIds: string[]): string | null {
	if (!models?.length) return null;

	const scoreModel = (m: Model): number => {
		const id = `${m.id}`.toLowerCase();
		const name = `${m.name ?? ''}`.toLowerCase();
		const s = `${id} ${name}`;
		let sc = 0;
		if (/\bgpt[-_]?5|gpt[-_]?4\.?5|gpt[-_]?4o|gpt[-_]?4\b/.test(s)) sc += 120;
		if (/\bo[13]\b|(^|[^a-z])o1([^a-z]|$)|o3/.test(s)) sc += 115;
		if (/claude.*(opus|sonnet|4)/.test(s)) sc += 110;
		if (/gemini.*(2\.|pro|ultra)/.test(s)) sc += 100;
		if (/deepseek.*(r1|v3)/.test(s)) sc += 75;
		if (/qwen.*(72|32|110)|llama.*(405|70)/.test(s)) sc += 60;
		if (/mistral.*large|mixtral|command-r\+?/.test(s)) sc += 55;
		if (/\b(8b|7b|3b|1\.5b|tiny|mini)\b/.test(s)) sc -= 40;
		if (selectedIds?.includes(m.id)) sc += 12;
		return sc;
	};

	let best = models[0];
	let bestScore = scoreModel(best);
	for (let i = 1; i < models.length; i++) {
		const sc = scoreModel(models[i]);
		if (sc > bestScore) {
			bestScore = sc;
			best = models[i];
		}
	}
	return best?.id ?? null;
}

export function normalizePromptForCompare(a: string, b: string): boolean {
	return (
		a.trim().replace(/\s+/g, ' ') ===
		b.trim().replace(/\s+/g, ' ')
	);
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
