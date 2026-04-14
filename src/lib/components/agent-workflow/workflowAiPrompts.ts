/**
 * LLM prompts for AI-assisted workflow authoring (draft graph + node field hints).
 * Keep in sync with validate.ts, serialization.ts, and backend node types.
 */

import type { Model } from '$lib/stores';

import type { AgentWorkflowV1 } from './types';

export const WORKFLOW_GENERATOR_SYSTEM = `You compile natural language into ONE JSON object for Open WebUI Agent workflows (a directed acyclic graph).

### OUTPUT (strict)
- Return a SINGLE JSON object only — no markdown fences, no commentary.
- Shape: {"version":2,"startNodeId":"<trigger id>","nodes":[...],"edges":[...]}
- JSON.parse-safe: double-quoted keys and strings; no trailing commas; no // or /* */ comments; no unquoted keys.
- Every node MUST include "nodeType" as one of: "trigger", "if_else", "transform", "agent", "http_request", "telegram", "merge", "group". Never omit nodeType (omission is interpreted as agent and breaks routing).

### PRE-OUTPUT CHECKLIST (every item must pass — empty config or missing edges breaks the UI)
1) startNodeId is exactly the id of the **only** trigger node in almost every flow. **Do NOT add a second trigger** unless the user explicitly needs two independent entry points (e.g. two separate webhooks). Russian phrases like «первый триггер, потом второй триггер», «после триггера обычный триггер», «trigger then another trigger» usually mean *the next step after start* (if_else, agent, …), NOT a second trigger block — use **one** trigger → if_else (or next real block).
2) There is an edge from that trigger to the if_else (or first router) node — never leave the trigger with zero outgoing edges when an if_else exists.
3) Every if_else that has two branches has TWO outgoing edges with "sourceHandle":"true" and "sourceHandle":"false" (lowercase strings). Never omit sourceHandle on IF branches.
4) Substring routing: for "contains" / "substring" / "подстрока" requests set "conditionMode":"substring" and put the searched token in "condition" (non-empty string, e.g. refund). An IF in substring mode with an empty "condition" is INVALID.
5) Fixed text on branches: each transform that should emit a constant string must have "config.template" set to that exact string — not "{{input}}" and not empty unless the user explicitly asked to pass input through.
6) If the user asked only for trigger + IF + two fixed outputs with no LLM: use two transform nodes as branch leaves — do NOT add agent nodes and do NOT chain transform→agent.
7) Each non-merge node has exactly one incoming edge; trigger has none; merge has two+.
8) **Branch convergence:** If two different upstream nodes must both feed the SAME downstream node (e.g. true-branch Telegram and false-branch Agent both → one final Telegram), you MUST NOT wire both into that downstream node. Insert a **merge** node: upstreamA → merge, upstreamB → merge, merge → sharedDownstream. Incoming edges into merge use no sourceHandle; omit "when" or set "when":"always" only. Merge has exactly ONE outgoing edge.
9) Every node has "position":{"x":number,"y":number} (space nodes ~240px apart).

### NODE TYPES (nodeType)
- trigger — config: {"label":string,"triggerMode":"manual"|"schedule"|"webhook"} (usually manual).
- if_else — choose ONE mode:
  • Substring in user text: "conditionMode":"substring", "condition":"<token>", "conditionExpression":"" (plus defaults jsonPath "items.0.json.userInput", jsonOperator "equals", compareValue "" if unused).
  • Exact equality on user message: "conditionMode":"json", "jsonPath":"items.0.json.userInput", "jsonOperator":"equals", "compareValue":"<exact>".
  • Formula: "conditionMode":"expression", "conditionExpression":"=..."
- transform — config: {"template":string}. Use literal text for fixed replies; use {{input}} only when forwarding/transforming input.
- agent — only when an LLM or image step is required: agentName, modelId from AVAILABLE MODEL IDS (or "default"), mode text|image, full task. Skip agents for pure routing + fixed strings.
- http_request, group — only if explicitly requested.
- **merge** — REQUIRED whenever two branches must join one shared node (see checklist item 8). Config typically includes "separator" (e.g. "\\n---\\n") to combine inputs.
- telegram — send Telegram message: config includes credentialMode "env"|"inline", botToken or botTokenEnv (default TELEGRAM_BOT_TOKEN), chatId (numeric id), messageText (templates {{input}} ok), parseMode optional ""|"HTML"|"MarkdownV2". Never put real tokens in JSON for production; use env.

### EDGE OBJECTS
{"id":"unique","fromNodeId":"...","toNodeId":"..."} and for IF branches add "sourceHandle":"true" or "false".

Canonical minimal graph (fixed text, two branches):
- Edge 1: triggerId → ifElseId (no sourceHandle).
- Edge 2: ifElseId → transformTrueId with "sourceHandle":"true".
- Edge 3: ifElseId → transformFalseId with "sourceHandle":"false".
Do not wire trigger → branch transform when if_else already connects to that transform (double incoming).

Converging branches (two paths → one Telegram/agent):
- Wrong: telegramTrue → finalTg AND agentFalse → finalTg (two incoming to finalTg — INVALID).
- Right: telegramTrue → mergeId, agentFalse → mergeId, mergeId → finalTg (merge has two incoming, finalTg has one).
- **If user asked for Telegram on the true branch:** use **nodeType "telegram"** for that send, not a transform labeled like Telegram. Transforms do not send to Telegram.
- **Full pattern (substring IF → TG on true, agent on false, then one final TG):** trigger → if_else; if_else true → **telegram_true** → merge; if_else false → **agent** → merge; merge → **telegram_final**. Both branch tails must reach merge so merge has ≥2 inputs.

### COMMON MISTAKES (avoid)
- Dead-end branch: if_else true → transform only, with no edge to merge or telegram — INVALID if user wanted true → Telegram then join.
- Merge with only one incoming when two branches should meet — add the missing edge from the other branch (e.g. true-path telegram → merge).
- Extra trigger in the middle of the canvas — remove; use one start trigger only unless explicitly required.

### CONFIG SNIPPET (substring IF + two literals — copy field values; use your own ids/positions)
if_else config:
{"condition":"refund","conditionMode":"substring","conditionExpression":"","jsonPath":"items.0.json.userInput","jsonOperator":"equals","compareValue":""}
transform configs:
{"template":"Refund request detected"} and {"template":"General inquiry"}
If the user quoted fixed phrases in English, keep that exact English in "template".

### IDENTIFIERS
UUID-like unique ids for every node and edge. For every node, "agentId" === "id".

SECRETS: never embed API keys.

Return ONLY the JSON object.`;

/**
 * Pass 1 (optional): turn colloquial / ambiguous text into a compact spec for the JSON generator.
 * Keeps quoted tokens; does not output workflow JSON.
 */
export const WORKFLOW_INTENT_REWRITER_SYSTEM = `You rewrite informal workflow descriptions into a short, unambiguous specification for a graph builder.

OUTPUT
- 8–20 short lines in English (node type names: trigger, if_else, merge, telegram, agent, transform).
- No JSON. No markdown code fences. Bullet lines or numbered lines only.

RULES
- **One trigger** as workflow start unless the user clearly needs two independent entry points (e.g. two webhooks). Phrases like «первый триггер, потом второй», "first trigger then second trigger", "после триггера обычный триггер" usually mean the **next step** (if_else / router), NOT a second trigger block.
- **Substring IF:** state conditionMode substring and the exact token in quotes when the user gave one.
- **Telegram:** if they asked to send via Telegram, say **telegram** nodes — do not describe them as generic "transform" unless they only want static text with no send.
- **Convergence:** if both branches must reach one shared step (e.g. final Telegram), spell out: true-branch tail → merge, false-branch tail → merge, merge → final telegram (never two edges into one non-merge node).
- Preserve user language for literal strings that must appear in configs (quoted substrings, fixed messages).`;

export function workflowIntentRewriterUserPrompt(userDescription: string): string {
	return `Rewrite into a clear workflow specification:\n\n${userDescription.trim()}`;
}

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

export const WORKFLOW_PATCH_EDITOR_SYSTEM = `You are a workflow PATCH editor for Open WebUI "Agent workflows".

MODE: MODIFY EXISTING WORKFLOW — do NOT regenerate the whole graph from scratch unless the user explicitly asks to replace everything.

You receive:
- currentWorkflow: the full current JSON graph (nodes, edges, startNodeId, configs).
- userRequest: what the user wants to change.

OUTPUT (STRICT)
- Respond with ONE JSON object only — no markdown fences, no commentary.
- Shape: { "operations": [ ... ] } and optionally "previewWorkflow": { full graph } for validation hints only.

OPERATIONS (use only these "type" values)
- { "type": "add_node", "node": <AgentWorkflowNodeV1> } — new nodes MUST use new unique ids (UUID-like). Set agentId === id for agent nodes.
- { "type": "update_node", "nodeId": "<existing id>", "changes": { partial fields } } — shallow merge at top level; merge "config" objects. NEVER change node id via update.
- { "type": "remove_node", "nodeId": "<id>" } — do not remove unless user asked; removing the start node requires a prior "set_start_node" to another trigger if applicable.
- { "type": "add_edge", "edge": { "id", "fromNodeId", "toNodeId", "sourceHandle"?, "when"? } }
- { "type": "remove_edge", "edgeId": "<id>" }
- { "type": "set_start_node", "startNodeId": "<id>" } — only when needed.

CHECKLIST (same as full graph generation)
- add_edge: trigger → if_else if missing; if_else → each branch with sourceHandle true/false.
- update_node config: substring IF must have non-empty "condition"; transforms must have literal "template" when user gave fixed phrases.
- No extra agent nodes when user asked for transform-only branch ends.
- If two branches must feed one shared node: add_node merge, add_edge branchA→merge and branchB→merge (when always or omit), add_edge merge→shared; remove any second incoming edge into the shared node.

RULES
- If the graph has an extra trigger the user did not want (often from «второй триггер» wording), remove that trigger node and its edges, and wire the main trigger → if_else.
- Preserve existing nodes and edges unless the user explicitly asks to remove or replace them.
- Reuse existing node IDs for unchanged nodes — never invent new ids for nodes that stay.
- Only new nodes get new ids.
- Operation order: list every add_node for NEW blocks before add_edge lines that reference those ids (edges may be applied after nodes automatically; endpoint ids must exist).
- Keep the graph valid: single trigger as start, IF edges need sourceHandle "true"/"false", merge rules, reachability.
- Apply the smallest set of operations that satisfies the user request.
- Model ids for NEW or UPDATED agent nodes must come from AVAILABLE MODEL IDS when that block is present (copy verbatim).
- When the user specifies substring IF or fixed transform text, use update_node with merged "config": if_else must include non-empty "condition" (substring) and "conditionMode":"substring"; transform must set "template" to the exact literal string — never leave defaults like "{{input}}" or empty condition if the user gave concrete phrases.
- If the user wants fixed text per IF branch and forbids extra agents, use only transform nodes on the branches — remove_node for redundant agents (and remove_edge first if needed) so the graph is trigger → if_else → two transforms.

previewWorkflow (optional): if you include it, it must be a full valid graph after operations would be applied — used for sanity check only.

Return ONLY the JSON object.`;

/** Soft-truncate long text fields so the full structure (nodes/edges) fits context. */
export function trimWorkflowJsonForEditPrompt(wf: AgentWorkflowV1): AgentWorkflowV1 {
	const maxTask = 4000;
	const copy = JSON.parse(JSON.stringify(wf)) as AgentWorkflowV1;
	for (const n of copy.nodes) {
		if (typeof n.task === 'string' && n.task.length > maxTask) {
			n.task = `${n.task.slice(0, maxTask)}\n…[truncated]`;
		}
	}
	return copy;
}

export function workflowPatchUserPrompt(
	userRequest: string,
	currentWorkflowJson: string,
	modelCatalogBlock: string
): string {
	return `currentWorkflow (authoritative — preserve unless change is requested):
${currentWorkflowJson}

userRequest:
${userRequest.trim()}
${modelCatalogBlock}

Return ONLY: { "operations": [ ... ] } per system rules (optional "previewWorkflow").`;
}

export function workflowPatchRepairUserPrompt(
	userRequest: string,
	currentWorkflowJson: string,
	failureReason: string,
	rawModelOutput: string,
	modelCatalogBlock: string
): string {
	const snippet =
		rawModelOutput.length > 8000 ? rawModelOutput.slice(0, 8000) + '\n…[truncated]' : rawModelOutput;
	return `Your previous PATCH output was invalid or could not be applied.

Failure: ${failureReason}

Previous output:
${snippet}

currentWorkflow:
${currentWorkflowJson}

userRequest:
${userRequest.trim()}
${modelCatalogBlock}

Return ONLY a corrected JSON object: { "operations": [ ... ] } (optional previewWorkflow). No markdown.`;
}

export function workflowGeneratorUserPrompt(
	userDescription: string,
	modelCatalogBlock: string
): string {
	return `User description — encode EVERY concrete detail they name (substrings, fixed phrases, branch wiring). Infer only what is clearly implied.

${userDescription.trim()}
${modelCatalogBlock}

Requirements:
- **One trigger** as start (unless they clearly ask for two separate entry points). Ignore colloquial «second trigger» as a second trigger block — wire trigger → if_else.
- Edges: trigger must connect to if_else; if_else must connect to both branch targets with sourceHandle true and false.
- if_else in substring mode: non-empty config.condition with the token to search; non-empty templates on transforms when they gave exact output text.
- **Telegram sends:** use nodeType **telegram** wherever they asked for Telegram/API send; do not substitute a plain transform for “send to Telegram” unless they only want static text without sending.
- If they forbid extra agents / want only transforms at the ends, use only trigger + if_else + two transforms.
- If both branches must end at the same downstream step (e.g. true → Telegram, false → agent, then one final Telegram): **telegram_true → merge**, **agent → merge**, **merge → telegram_final** — merge must have **both** incoming edges.

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
	const hint =
		failureReason.includes('unreachable')
			? ' Ensure every node has a path of edges from startNodeId; for if_else both branches must connect to their target nodes with sourceHandle true/false; include trigger → if_else.'
			: failureReason.includes('multiple_incoming_not_supported')
				? ' Two edges entered the same non-merge node. Insert a merge node: connect each branch output into merge (no sourceHandle on those edges; when omitted or "always"), then ONE edge merge → shared target. Remove duplicate edges into the shared node.'
				: failureReason.includes('merge_needs_two_inputs')
					? ' Each merge node needs at least TWO incoming edges from different upstream nodes.'
					: failureReason.includes('merge_too_many_outgoing')
						? ' Each merge node must have exactly ONE outgoing edge.'
						: failureReason.includes('merge_edges_must_be_always')
							? ' Edges into merge must use when "always" only (or omit when).'
							: /validation:.*(if_else|if_too_many)/i.test(failureReason)
								? ' For if_else outgoing edges, each MUST include sourceHandle "true" or "false".'
								: failureReason.includes('json_parse')
					? ' Output must be strict JSON: double-quoted keys and strings only; no trailing commas; no comments.'
					: /extract_json|Unclosed|bracket|nesting/i.test(failureReason)
						? ' Your previous reply was CUT OFF or incomplete — output a COMPLETE single JSON object from first { to final } (all brackets closed). Keep the graph minimal (short ids, no prose).'
						: '';
	return `Your previous output was invalid or failed validation.

Failure: ${failureReason}${hint}

Previous model output (may include extra text; fix structure):
${snippet}

Original user description:
${originalDescription.trim()}
${modelCatalogBlock}

Return ONLY one corrected JSON object (same schema). No markdown fences, no explanation.
Fill every if_else substring "condition" and every fixed-text transform "template" from the original description — do not leave them empty.`;
}

export const NODE_FIELD_HINTS_SYSTEM = `You are a workflow node field assistant for Open WebUI agent workflows.

You receive the current workflow JSON (or summary) and ONE selected node (type + data + id).

TASK
Suggest concrete values for that node's fields (task, template, jsonPath, compareValue, url, headersJson, body, mode, modelId hints, telegram chatId/messageText, etc.).
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
