/**
 * LLM prompts for AI-assisted workflow authoring (draft graph + node field hints).
 * Keep in sync with validate.ts, serialization.ts, and backend node types.
 */

import type { Model } from '$lib/stores';

export const WORKFLOW_GENERATOR_SYSTEM = `You are an expert workflow graph compiler for Open WebUI "Agent workflows" (DAG editor).

GOAL
Convert the user's natural-language description into ONE valid workflow JSON. Infer intent deeply: if they ask for prompt refinement then image generation with a style (e.g. black and white), you MUST encode that in agent "mode" and long, precise "task" strings — not empty or generic placeholders.

OUTPUT RULES (STRICT)
- Respond with a SINGLE JSON object only — no markdown code fences, no commentary before or after.
- Top-level: { "version": 2, "startNodeId": "<trigger node id>", "nodes": [ ... ], "edges": [ ... ] }

AGENT NODES (most important)
Each "agent" node MUST include:
- "nodeType": "agent"
- "agentName": short label (shown on canvas)
- "agentId": same as "id"
- "modelId": MUST be copied EXACTLY from the AVAILABLE MODEL IDS list when that block is present in the user message. Pick a model with image_generation: true for image steps; pick a chat/text model for text steps. If no list is present, use "default".
- "mode": "text" | "image"
  - Use "text" for: rewriting prompts, classification, summarizing, JSON extraction, any LLM-only step.
  - Use "image" ONLY for steps that must call an image-generation model (diffusion, etc.).
- "task": A FULL multi-sentence instruction for THIS step only (like a system prompt for that step). Include:
  - What the step receives (usually previous step output / user message from trigger wire).
  - What to output (e.g. "output only the refined prompt text" for a refiner).
  - For image mode: explicit visual requirements from the user (e.g. black and white, high contrast, subject matter) and that the model should use the previous step's text as the image prompt / basis.
- Write "task" in the same language as the user's description when they are not writing in English.

Example pattern (two agents): first agent mode "text" task explains to read user input and previous context and output an improved prompt; second agent mode "image" task explains to generate an image from the previous step's text with the requested style.

NODE TYPES (field "nodeType")
- "trigger" — config: { "label": string, "triggerMode": "manual" | "schedule" | "webhook" } (usually "manual").
- "if_else" — branching; config: conditionMode "substring" | "json" | "expression"; use conditionExpression for formulas like "={{$json.age > 18}}" (preferred when you need comparisons); jsonPath often "items.0.json.userInput" for json mode.
- "transform" — config: { "template": string } with {{input}}, {{json}}.
- "http_request" — server HTTP; config method, url, headersJson, body, timeoutSeconds, followRedirects.
- "merge" — needs two+ incoming edges; config separator.
- "group" — omit unless asked.

IDENTIFIERS
- Unique ids (UUID-like) for every node and edge.
- Every node: "agentId" === "id".

GRAPH RULES
- One trigger; it is startNodeId; no incoming edges to trigger.
- Non-merge nodes: exactly one incoming edge. Merge: two+ incoming.
- All executable nodes reachable from start; chain edges left-to-right (trigger → a → b → …).
- if_else: at most two outgoing edges with sourceHandle "true" / "false" when two branches.

POSITIONS
- "position": { "x", "y" }; space nodes ~240px apart horizontally.

SECRETS: never put API keys in JSON.

Return ONLY the JSON object.`;

/** Appends the live model catalog so the LLM can set concrete modelId values. */
export function buildModelCatalogForPrompt(models: Model[] | undefined): string {
	const list = models ?? [];
	if (!list.length) {
		return '';
	}
	const lines = list.slice(0, 96).map((m) => {
		const ig =
			(m.info?.meta?.capabilities as Record<string, boolean> | undefined)?.image_generation ===
			true;
		const nm = (m.name || m.id || '').slice(0, 96);
		return `- id "${m.id}" | name: ${nm} | image_generation: ${ig}`;
	});
	return `

AVAILABLE MODEL IDS (required when this block is non-empty)
Each agent node's "modelId" MUST be exactly one of the "id" strings below (copy verbatim).
For agents with mode "image", choose an id where image_generation is true when possible.
For agents with mode "text", choose an id where image_generation is false when possible.

${lines.join('\n')}
`;
}

export function workflowGeneratorUserPrompt(
	userDescription: string,
	modelCatalogBlock: string
): string {
	return `User description (infer all steps, modes, and detailed task text):

${userDescription.trim()}
${modelCatalogBlock}

Produce the workflow JSON per system rules.`;
}

export function workflowRepairUserPrompt(
	originalDescription: string,
	failureReason: string,
	rawModelOutput: string,
	modelCatalogBlock: string
): string {
	const snippet =
		rawModelOutput.length > 12000 ? rawModelOutput.slice(0, 12000) + '\n…[truncated]' : rawModelOutput;
	return `Your previous output was invalid or failed validation.

Failure: ${failureReason}

Previous model output (may include extra text; fix structure):
${snippet}

Original user description:
${originalDescription.trim()}
${modelCatalogBlock}

Return ONLY one corrected JSON object (same schema). No markdown fences, no explanation.`;
}

export const NODE_FIELD_HINTS_SYSTEM = `You are a workflow node field assistant for Open WebUI agent workflows.

You receive the current workflow JSON (or summary) and ONE selected node (type + data + id).

TASK
Suggest concrete values for that node's fields (task, template, jsonPath, compareValue, url, headersJson, body, mode, modelId hints, etc.).
Explain wire context: previous step output is n8n-style { "$wf": 1, "items": [ { "json": { ... } } ], "text": "..." }.

RULES
- Output 5–12 short bullet lines: "field → suggested value — why".
- For agent nodes: propose a full "task" string and whether mode should be text or image.
- Never output real secrets; reference env or connectors later.
- Match the user's language when obvious; otherwise English.

Do NOT output raw JSON of the whole workflow — only bullet suggestions.`;

export function nodeFieldHintsUserPrompt(
	workflowJsonCompact: string,
	selectedNodeJson: string
): string {
	return `Current workflow (compact JSON):
${workflowJsonCompact}

Selected node (focus):
${selectedNodeJson}

Give field suggestions as bullets.`;
}
