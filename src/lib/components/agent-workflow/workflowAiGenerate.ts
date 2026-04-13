import { generateOpenAIChatCompletion } from '$lib/apis/openai';
import { WEBUI_BASE_URL } from '$lib/constants';
import type { Model } from '$lib/stores';

import type { AgentWorkflowV1 } from './types';
import { normalizeWorkflowForLoad } from './serialization';
import { validateAgentWorkflow } from './validate';
import { resolveAgentModelsInWorkflow } from './workflowAgentModelResolve';
import { repairWorkflowReachability } from './workflowGraphRepair';
import {
	NODE_FIELD_HINTS_SYSTEM,
	WORKFLOW_GENERATOR_SYSTEM,
	buildModelCatalogForPrompt,
	nodeFieldHintsUserPrompt,
	workflowGeneratorUserPrompt,
	workflowRepairUserPrompt
} from './workflowAiPrompts';

/** Strip fences / take outermost JSON object from LLM output. */
export function extractJsonObjectFromLlmText(raw: string): string {
	const t = raw.trim();
	const fence = /```(?:json)?\s*([\s\S]*?)```/;
	const fm = t.match(fence);
	if (fm?.[1]) {
		return fm[1].trim();
	}
	const i0 = t.indexOf('{');
	const i1 = t.lastIndexOf('}');
	if (i0 !== -1 && i1 >= i0) {
		return t.slice(i0, i1 + 1);
	}
	throw new Error('No JSON object found in model output');
}

function isWorkflowShape(v: unknown): v is AgentWorkflowV1 {
	if (!v || typeof v !== 'object') return false;
	const o = v as Record<string, unknown>;
	return (
		Array.isArray(o.nodes) &&
		Array.isArray(o.edges) &&
		typeof o.startNodeId === 'string' &&
		o.startNodeId.length > 0
	);
}

export type GenerateWorkflowResult =
	| { ok: true; workflow: AgentWorkflowV1 }
	| { ok: false; error: string };

/**
 * Calls the configured chat model twice at most: initial draft, then repair if parse/validation fails.
 */
export async function generateWorkflowFromDescription(
	token: string,
	modelId: string,
	userDescription: string,
	defaultModelId: string,
	availableModels?: Model[]
): Promise<GenerateWorkflowResult> {
	const desc = userDescription.trim();
	if (!desc) {
		return { ok: false, error: 'empty_description' };
	}
	if (!modelId) {
		return { ok: false, error: 'no_model' };
	}

	const catalog = buildModelCatalogForPrompt(availableModels ?? []);

	let lastRaw = '';
	let lastFailure = '';

	for (let attempt = 0; attempt < 2; attempt++) {
		const userContent =
			attempt === 0
				? workflowGeneratorUserPrompt(desc, catalog)
				: workflowRepairUserPrompt(desc, lastFailure, lastRaw, catalog);

		let res: Awaited<ReturnType<typeof generateOpenAIChatCompletion>>;
		try {
			res = await generateOpenAIChatCompletion(
				token,
				{
					model: modelId,
					stream: false,
					temperature: attempt === 0 ? 0.35 : 0.15,
					messages:
						attempt === 0
							? [
									{ role: 'system', content: WORKFLOW_GENERATOR_SYSTEM },
									{ role: 'user', content: userContent }
								]
							: [
									{ role: 'system', content: WORKFLOW_GENERATOR_SYSTEM },
									{ role: 'user', content: userContent }
								]
				},
				`${WEBUI_BASE_URL}/api`
			);
		} catch (e) {
			const msg = e instanceof Error ? e.message : String(e);
			return { ok: false, error: msg };
		}

		const raw = res?.choices?.[0]?.message?.content ?? '';
		if (!raw.trim()) {
			lastFailure = 'empty_model_response';
			lastRaw = '';
			continue;
		}
		lastRaw = raw;

		let jsonStr: string;
		try {
			jsonStr = extractJsonObjectFromLlmText(raw);
		} catch (e) {
			lastFailure = `extract_json: ${e instanceof Error ? e.message : String(e)}`;
			continue;
		}

		let parsed: unknown;
		try {
			parsed = JSON.parse(jsonStr);
		} catch (e) {
			lastFailure = `json_parse: ${e instanceof Error ? e.message : String(e)}`;
			continue;
		}

		if (!isWorkflowShape(parsed)) {
			lastFailure = 'invalid_workflow_shape';
			continue;
		}

		let migrated = normalizeWorkflowForLoad(parsed, defaultModelId);
		let v = validateAgentWorkflow(migrated);
		if (v) {
			const repaired = repairWorkflowReachability(migrated);
			const v2 = validateAgentWorkflow(repaired);
			if (!v2) {
				migrated = repaired;
				v = null;
			} else {
				v = v2;
			}
		}
		if (v) {
			lastFailure = `validation:${v}`;
			continue;
		}

		migrated = resolveAgentModelsInWorkflow(migrated, availableModels ?? [], defaultModelId);
		const vPost = validateAgentWorkflow(migrated);
		if (vPost) {
			lastFailure = `validation:${vPost}`;
			continue;
		}

		return { ok: true, workflow: migrated };
	}

	return { ok: false, error: lastFailure || 'generation_failed' };
}

export type NodeHintsResult = { ok: true; text: string } | { ok: false; error: string };

/**
 * Suggest field values for one selected node given full workflow context.
 */
export async function suggestNodeFieldsFromContext(
	token: string,
	modelId: string,
	workflow: AgentWorkflowV1,
	selectedNode: { id: string; type?: string; data?: Record<string, unknown>; position?: unknown }
): Promise<NodeHintsResult> {
	if (!modelId) {
		return { ok: false, error: 'no_model' };
	}
	let wfJson: string;
	try {
		wfJson = JSON.stringify(workflow).slice(0, 24000);
	} catch {
		return { ok: false, error: 'workflow_serialize' };
	}
	const selJson = JSON.stringify(selectedNode).slice(0, 8000);
	const userContent = nodeFieldHintsUserPrompt(wfJson, selJson);

	try {
		const res = await generateOpenAIChatCompletion(
			token,
			{
				model: modelId,
				stream: false,
				temperature: 0.4,
				messages: [
					{ role: 'system', content: NODE_FIELD_HINTS_SYSTEM },
					{ role: 'user', content: userContent }
				]
			},
			`${WEBUI_BASE_URL}/api`
		);
		const text = res?.choices?.[0]?.message?.content?.trim() ?? '';
		if (!text) {
			return { ok: false, error: 'empty_model_response' };
		}
		return { ok: true, text };
	} catch (e) {
		const msg = e instanceof Error ? e.message : String(e);
		return { ok: false, error: msg };
	}
}
