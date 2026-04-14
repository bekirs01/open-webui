/**
 * When the user clearly asked for trigger → IF (substring) → two transforms but the model
 * emitted all agent nodes (or missing routers), replace with a minimal valid graph and
 * let enrichWorkflowConfigFromUserDescription fill strings from the prompt.
 */

import type { AgentWorkflowV1 } from './types';
import { enrichWorkflowConfigFromUserDescription } from './workflowAiConfigHeuristics';

function newId(): string {
	if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
	return `n-${Date.now()}-${Math.random().toString(36).slice(2, 11)}`;
}

function newEdgeId(): string {
	if (typeof crypto !== 'undefined' && crypto.randomUUID) return `e-${crypto.randomUUID()}`;
	return `e-${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;
}

/** User text clearly describes IF + substring + two branch outputs (RU/EN). */
export function userWantsIfElseTwoFixedBranchRouting(description: string): boolean {
	const d = description.trim();
	if (d.length < 12) return false;
	const t = d.toLowerCase();
	const mentionsIf =
		/\b(if|иф)\b/i.test(d) ||
		/if_else/i.test(d) ||
		/узел\s+if/i.test(t) ||
		/узел\s*if/i.test(t);
	const mentionsSub =
		/substring|подстрок|подстрока/i.test(t) || /contains|содержит/i.test(t) || /"refund"/i.test(d);
	const mentionsBranchOutputs =
		/transform|трансформ/i.test(t) || /ветк|branch|true|false|истина|ложь/i.test(t);
	return mentionsIf && mentionsSub && mentionsBranchOutputs;
}

/** True when we already have the right block types (edges may still need repair). */
export function hasIfElseAndTwoTransforms(wf: AgentWorkflowV1): boolean {
	const trig = wf.nodes.filter((n) => n.nodeType === 'trigger').length >= 1;
	const ifs = wf.nodes.filter((n) => n.nodeType === 'if_else').length >= 1;
	const tr = wf.nodes.filter((n) => n.nodeType === 'transform').length >= 2;
	return trig && ifs && tr;
}

export function llmEmittedBrokenRoutingGraph(wf: AgentWorkflowV1): boolean {
	if (wf.nodes.length === 0) return true;
	if (hasIfElseAndTwoTransforms(wf)) return false;
	const agents = wf.nodes.filter((n) => n.nodeType === 'agent').length;
	if (agents === wf.nodes.length && wf.nodes.length >= 2) return true;
	const noRouter = wf.nodes.every((n) => n.nodeType !== 'if_else');
	const lowTransform = wf.nodes.filter((n) => n.nodeType === 'transform').length < 2;
	return noRouter && lowTransform;
}

export function buildMinimalIfElseTwoTransformWorkflow(): AgentWorkflowV1 {
	const tid = newId();
	const iid = newId();
	const tt = newId();
	const tf = newId();
	return {
		version: 2,
		startNodeId: tid,
		nodes: [
			{
				id: tid,
				nodeType: 'trigger',
				agentId: tid,
				position: { x: 80, y: 160 },
				config: { label: 'Trigger', triggerMode: 'manual' },
				task: '',
				agentName: '',
				modelId: '',
				mode: 'text'
			},
			{
				id: iid,
				nodeType: 'if_else',
				agentId: iid,
				position: { x: 380, y: 160 },
				config: {
					condition: '',
					conditionMode: 'substring',
					conditionExpression: '',
					jsonPath: 'items.0.json.userInput',
					jsonOperator: 'equals',
					compareValue: ''
				},
				task: '',
				agentName: '',
				modelId: '',
				mode: 'text'
			},
			{
				id: tt,
				nodeType: 'transform',
				agentId: tt,
				position: { x: 680, y: 80 },
				config: { template: '{{input}}' },
				task: '',
				agentName: '',
				modelId: '',
				mode: 'text'
			},
			{
				id: tf,
				nodeType: 'transform',
				agentId: tf,
				position: { x: 680, y: 240 },
				config: { template: '{{input}}' },
				task: '',
				agentName: '',
				modelId: '',
				mode: 'text'
			}
		],
		edges: [
			{ id: newEdgeId(), fromNodeId: tid, toNodeId: iid },
			{ id: newEdgeId(), fromNodeId: iid, toNodeId: tt, sourceHandle: 'true' },
			{ id: newEdgeId(), fromNodeId: iid, toNodeId: tf, sourceHandle: 'false' }
		]
	};
}

/**
 * If the prompt asks for IF + two branch transforms but the parsed graph is wrong, return a fixed graph.
 * Otherwise return null.
 */
export function tryReplaceWithCanonicalIfElseTwoTransforms(
	description: string,
	wf: AgentWorkflowV1
): AgentWorkflowV1 | null {
	if (!userWantsIfElseTwoFixedBranchRouting(description)) return null;
	if (!llmEmittedBrokenRoutingGraph(wf)) return null;
	let next = buildMinimalIfElseTwoTransformWorkflow();
	next = enrichWorkflowConfigFromUserDescription(description, next);
	return next;
}
