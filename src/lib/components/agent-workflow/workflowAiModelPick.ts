import type { Model } from '$lib/stores';

/** Heuristic: models that are poor choices for JSON / workflow drafting. */
const IMAGE_MODEL_ID_NAME = /dall-e|dalle|dall·e|flux|sdxl|stable-diffusion|stable_diffusion|midjourney|imagen|playground-v|qwen-image|sd3|kandinsky|wan-i2v|image-gen|text-to-image|txt2img/i;

/** True if model is meant for image generation (not a text LLM for agent steps). */
export function isLikelyImageOnlyModel(m: Model): boolean {
	const caps = m.info?.meta?.capabilities as Record<string, boolean | undefined> | undefined;
	if (caps?.image_generation === true) {
		return true;
	}
	const id = `${m.id} ${m.name ?? ''}`;
	return IMAGE_MODEL_ID_NAME.test(id);
}

function scoreModelForWorkflowDraft(m: Model): number {
	let s = 0;
	if (isLikelyImageOnlyModel(m)) {
		s -= 200;
	}
	const id = (m.id || '').toLowerCase();
	const name = `${m.name ?? ''}`.toLowerCase();
	// Prefer general instruction-following chat models for structured JSON.
	if (/gpt-4|gpt-4\.|gpt-5|o3|o1|claude|gemini|llama-3|llama3|qwen2|qwen3|mistral|mixtral|deepseek|command-r|phi-3|phi3/i.test(id)) {
		s += 40;
	}
	// Instruct / chat variants are better at following workflow JSON specs.
	if (/instruct|chat|it\b|turbo/i.test(id) || /instruct|chat/i.test(name)) {
		s += 25;
	}
	if (m.owned_by === 'openai' && !isLikelyImageOnlyModel(m)) {
		s += 15;
	}
	if (m.owned_by === 'ollama' && !isLikelyImageOnlyModel(m)) {
		s += 10;
	}
	return s;
}

/**
 * Picks a chat model suitable for workflow JSON generation (not image-generation models).
 * Falls back to the first model if everything looks image-only.
 */
export function pickDefaultWorkflowAiModelId(models: Model[] | undefined | null): string | null {
	const list = models ?? [];
	if (list.length === 0) {
		return null;
	}
	const ranked = [...list]
		.map((m) => ({ m, score: scoreModelForWorkflowDraft(m) }))
		.sort((a, b) => {
			const d = b.score - a.score;
			if (d !== 0) return d;
			return (a.m.id || '').localeCompare(b.m.id || '');
		});
	const best = ranked[0];
	if (best.score > -100) {
		return best.m.id;
	}
	// All scored as image-only heuristically — still return first id so generation can run.
	return list[0]?.id ?? null;
}

export function modelLabel(models: Model[], id: string): string {
	const m = models.find((x) => x.id === id);
	return (m?.name || m?.id || id).trim();
}
