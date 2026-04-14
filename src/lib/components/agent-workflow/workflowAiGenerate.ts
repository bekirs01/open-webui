import { generateOpenAIChatCompletion } from '$lib/apis/openai';
import { WEBUI_BASE_URL } from '$lib/constants';
import type { Model } from '$lib/stores';

import type { AgentWorkflowV1 } from './types';
import { normalizeWorkflowForLoad } from './serialization';
import { validateAgentWorkflow } from './validate';
import { resolveAgentModelsInWorkflow } from './workflowAgentModelResolve';
import { enrichWorkflowConfigFromUserDescription } from './workflowAiConfigHeuristics';
import { tryReplaceWithCanonicalIfElseTwoTransforms } from './workflowCanonicalIfRouting';
import {
	repairMultipleIncomingWithMerge,
	repairWorkflowReachability,
	stripRedundantTriggerFeed
} from './workflowGraphRepair';
import {
	NODE_FIELD_HINTS_SYSTEM,
	WORKFLOW_GENERATOR_SYSTEM,
	WORKFLOW_INTENT_REWRITER_SYSTEM,
	WORKFLOW_PATCH_EDITOR_SYSTEM,
	buildModelCatalogForPrompt,
	nodeFieldHintsUserPrompt,
	trimWorkflowJsonForEditPrompt,
	workflowGeneratorUserPrompt,
	workflowIntentRewriterUserPrompt,
	workflowPatchRepairUserPrompt,
	workflowPatchUserPrompt,
	workflowRepairUserPrompt
} from './workflowAiPrompts';
import { applyOperations, type WorkflowOperation } from './workflowPatch';
import {
	extractFirstBalancedJsonObject,
	extractLongestParseableJsonFromFirstBrace,
	parseJsonFromLlmOutput,
	repairLlmJsonForParse
} from './workflowJsonParse';

/** Re-export for callers that only need string repair. */
export { repairLlmJsonForParse } from './workflowJsonParse';

/**
 * Completion budget for workflow JSON. Must leave room for system + user prompt under the model's
 * **total** context limit (prompt tokens + max_tokens ≤ context window). 16384 completion on a 16k
 * window model always fails once the prompt is non-trivial.
 */
const WORKFLOW_GEN_MAX_COMPLETION_TOKENS = 8192;
/** Budget for intent rewrite pass (plain text, short). */
const WORKFLOW_INTENT_MAX_COMPLETION_TOKENS = 1024;

async function rewriteWorkflowIntentSpec(
	token: string,
	modelId: string,
	userDescription: string
): Promise<string | null> {
	try {
		const res = await generateOpenAIChatCompletion(
			token,
			{
				model: modelId,
				stream: false,
				max_tokens: WORKFLOW_INTENT_MAX_COMPLETION_TOKENS,
				temperature: 0.12,
				messages: [
					{ role: 'system', content: WORKFLOW_INTENT_REWRITER_SYSTEM },
					{ role: 'user', content: workflowIntentRewriterUserPrompt(userDescription) }
				]
			},
			`${WEBUI_BASE_URL}/api`
		);
		const text = res?.choices?.[0]?.message?.content?.trim() ?? '';
		if (!text || text.length < 16) return null;
		return text;
	} catch {
		return null;
	}
}

/** Strip fences / take first balanced `{...}` from LLM output (string-safe). */
export function extractJsonObjectFromLlmText(raw: string): string {
	let t = raw.trim();
	t = t.replace(/<redacted_thinking>[\s\S]*?<\/think>/gi, '');
	t = t.replace(/<redacted_thinking>[\s\S]*?<\/think>/gi, '');
	t = t.replace(/<reasoning>[\s\S]*?<\/reasoning>/gi, '');
	t = t.trim();
	const fence = /```(?:json)?\s*([\s\S]*?)```/;
	const fm = t.match(fence);
	const body = fm?.[1] ?? t;
	try {
		return extractFirstBalancedJsonObject(body);
	} catch (e) {
		const start = body.indexOf('{');
		if (start < 0) {
			throw e instanceof Error ? e : new Error(String(e));
		}
		const greedy = extractLongestParseableJsonFromFirstBrace(body.slice(start));
		if (greedy) {
			return greedy;
		}
		throw e instanceof Error ? e : new Error(String(e));
	}
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

function isPatchEnvelope(v: unknown): v is { operations: WorkflowOperation[]; previewWorkflow?: AgentWorkflowV1 } {
	if (!v || typeof v !== 'object') return false;
	const o = v as Record<string, unknown>;
	if (!Array.isArray(o.operations)) return false;
	return true;
}

export type GenerateWorkflowResult =
	| { ok: true; workflow: AgentWorkflowV1; normalizedDescription?: string }
	| { ok: false; error: string };

/**
 * Calls the chat model up to three times: draft, then repair passes if parse/validation fails.
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

	const intentSpec = await rewriteWorkflowIntentSpec(token, modelId, desc);
	const generationBrief = intentSpec
		? `${intentSpec}\n\n---\nOriginal user text (preserve quoted tokens / phrases):\n${desc}`
		: desc;

	let lastRaw = '';
	let lastFailure = '';

	for (let attempt = 0; attempt < 3; attempt++) {
		const userContent =
			attempt === 0
				? workflowGeneratorUserPrompt(generationBrief, catalog)
				: workflowRepairUserPrompt(generationBrief, lastFailure, lastRaw, catalog);

		let res: Awaited<ReturnType<typeof generateOpenAIChatCompletion>>;
		try {
			res = await generateOpenAIChatCompletion(
				token,
				{
					model: modelId,
					stream: false,
					max_tokens: WORKFLOW_GEN_MAX_COMPLETION_TOKENS,
					temperature: attempt === 0 ? 0.22 : 0.12,
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
			parsed = parseJsonFromLlmOutput(jsonStr);
		} catch (e) {
			lastFailure = `json_parse: ${e instanceof Error ? e.message : String(e)}`;
			continue;
		}

		if (!isWorkflowShape(parsed)) {
			lastFailure = 'invalid_workflow_shape';
			continue;
		}

		let migrated = normalizeWorkflowForLoad(parsed, defaultModelId);
		const canonical = tryReplaceWithCanonicalIfElseTwoTransforms(desc, migrated);
		if (canonical) migrated = canonical;
		// Always repair (trigger→if_else, branch handles, strip bad trigger feeds) — do not only when validation fails.
		migrated = repairWorkflowReachability(migrated);
		migrated = repairMultipleIncomingWithMerge(migrated);
		migrated = stripRedundantTriggerFeed(migrated);
		migrated = enrichWorkflowConfigFromUserDescription(desc, migrated);
		migrated = resolveAgentModelsInWorkflow(migrated, availableModels ?? [], defaultModelId);
		const v = validateAgentWorkflow(migrated);
		if (v) {
			lastFailure = `validation:${v}`;
			continue;
		}

		return { ok: true, workflow: migrated, normalizedDescription: intentSpec ?? undefined };
	}

	return { ok: false, error: lastFailure || 'generation_failed' };
}

/**
 * EDIT MODE: applies a PATCH (operations[]) on top of currentWorkflow. Canvas is unchanged on failure.
 */
export async function editWorkflowWithPatch(
	token: string,
	modelId: string,
	userRequest: string,
	currentWorkflow: AgentWorkflowV1,
	defaultModelId: string,
	availableModels?: Model[]
): Promise<GenerateWorkflowResult> {
	const req = userRequest.trim();
	if (!req) {
		return { ok: false, error: 'empty_description' };
	}
	if (!modelId) {
		return { ok: false, error: 'no_model' };
	}

	const catalog = buildModelCatalogForPrompt(availableModels ?? []);
	const trimmed = trimWorkflowJsonForEditPrompt(currentWorkflow);
	let wfJson: string;
	try {
		wfJson = JSON.stringify(trimmed);
	} catch {
		return { ok: false, error: 'workflow_serialize' };
	}

	let lastRaw = '';
	let lastFailure = '';

	for (let attempt = 0; attempt < 3; attempt++) {
		const userContent =
			attempt === 0
				? workflowPatchUserPrompt(req, wfJson, catalog)
				: workflowPatchRepairUserPrompt(req, wfJson, lastFailure, lastRaw, catalog);

		let res: Awaited<ReturnType<typeof generateOpenAIChatCompletion>>;
		try {
			res = await generateOpenAIChatCompletion(
				token,
				{
					model: modelId,
					stream: false,
					max_tokens: WORKFLOW_GEN_MAX_COMPLETION_TOKENS,
					temperature: attempt === 0 ? 0.25 : 0.1,
					messages:
						attempt === 0
							? [
									{ role: 'system', content: WORKFLOW_PATCH_EDITOR_SYSTEM },
									{ role: 'user', content: userContent }
								]
							: [
									{ role: 'system', content: WORKFLOW_PATCH_EDITOR_SYSTEM },
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
			parsed = parseJsonFromLlmOutput(jsonStr);
		} catch (e) {
			lastFailure = `json_parse: ${e instanceof Error ? e.message : String(e)}`;
			continue;
		}

		if (!isPatchEnvelope(parsed)) {
			lastFailure = 'invalid_patch_envelope';
			continue;
		}

		const applied = applyOperations(currentWorkflow, parsed.operations);
		if (!applied.ok) {
			lastFailure = applied.error;
			continue;
		}

		let migrated = normalizeWorkflowForLoad(applied.workflow, defaultModelId);
		const canonical = tryReplaceWithCanonicalIfElseTwoTransforms(req, migrated);
		if (canonical) migrated = canonical;
		migrated = repairWorkflowReachability(migrated);
		migrated = repairMultipleIncomingWithMerge(migrated);
		migrated = stripRedundantTriggerFeed(migrated);
		migrated = enrichWorkflowConfigFromUserDescription(req, migrated);
		migrated = resolveAgentModelsInWorkflow(migrated, availableModels ?? [], defaultModelId);
		const vPost = validateAgentWorkflow(migrated);
		if (vPost) {
			lastFailure = `validation:${vPost}`;
			continue;
		}

		return { ok: true, workflow: migrated };
	}

	return { ok: false, error: lastFailure || 'patch_failed' };
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
