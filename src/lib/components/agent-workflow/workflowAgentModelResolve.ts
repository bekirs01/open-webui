import type { Model } from '$lib/stores';

import type { AgentWorkflowV1 } from './types';
import { isLikelyImageOnlyModel, pickDefaultWorkflowAiModelId } from './workflowAiModelPick';

function caps(m: Model | undefined): Record<string, boolean | undefined> | undefined {
	return m?.info?.meta?.capabilities as Record<string, boolean | undefined> | undefined;
}

/** True if Open WebUI marks this model as capable of image generation. */
export function modelHasImageGenerationCapability(m: Model | undefined): boolean {
	if (!m) return false;
	if (caps(m)?.image_generation === true) return true;
	return /qwen-image|dall-?e|flux|sdxl|stable-diffusion|imagen|wan-i2v|kandinsky|midjourney|text-to-image/i.test(
		`${m.id} ${m.name ?? ''}`
	);
}

/**
 * Prefer models explicitly tagged for image_generation, then name heuristics.
 */
export function pickDefaultImageAgentModelId(models: Model[]): string | null {
	const list = models ?? [];
	const tagged = list.filter((m) => caps(m)?.image_generation === true);
	if (tagged.length) {
		return tagged[0].id;
	}
	const heur = list.filter((m) => modelHasImageGenerationCapability(m));
	return heur[0]?.id ?? null;
}

/**
 * After LLM draft: ensure each agent uses a real modelId — text LLM for mode=text, image-capable for mode=image.
 */
export function resolveAgentModelsInWorkflow(
	wf: AgentWorkflowV1,
	models: Model[],
	fallbackId: string
): AgentWorkflowV1 {
	const textFallback = pickDefaultWorkflowAiModelId(models) || fallbackId;
	const imageFallback = pickDefaultImageAgentModelId(models) || textFallback;

	const nodes = wf.nodes.map((n) => {
		if (n.nodeType !== 'agent') {
			return n;
		}
		const mode = String(n.mode || 'text').toLowerCase() === 'image' ? 'image' : 'text';
		const cur = (n.modelId || '').trim();
		const found = models.find((m) => m.id === cur);
		const inList = Boolean(found);

		let modelId = cur;
		if (mode === 'image') {
			if (!cur || cur === 'default' || !inList || !modelHasImageGenerationCapability(found)) {
				modelId = imageFallback;
			}
		} else {
			if (!cur || cur === 'default' || !inList || (found && isLikelyImageOnlyModel(found))) {
				modelId = textFallback;
			}
		}

		return {
			...n,
			mode: mode as 'text' | 'image',
			modelId
		};
	});

	return { ...wf, nodes };
}
