import { describe, expect, it } from 'vitest';
import {
	enrichWorkflowConfigFromUserDescription,
	extractQuotedStrings,
	extractSubstringSearchToken
} from './workflowAiConfigHeuristics';
import type { AgentWorkflowV1 } from './types';

describe('workflowAiConfigHeuristics', () => {
	it('extractSubstringSearchToken finds refund from RU prompt', () => {
		const s = `- IF: подстрока "refund" без учёта регистра.\n- TRUE — "Refund request detected".\n- FALSE — "General inquiry".`;
		expect(extractSubstringSearchToken(s)).toBe('refund');
	});

	it('extractQuotedStrings preserves order', () => {
		const s = `foo "refund" bar «Refund request detected» 'General inquiry'`;
		expect(extractQuotedStrings(s)).toEqual([
			'refund',
			'Refund request detected',
			'General inquiry'
		]);
	});

	it('enrich fills empty if_else condition and transform templates', () => {
		const wf: AgentWorkflowV1 = {
			version: 2,
			startNodeId: 't1',
			nodes: [
				{
					id: 't1',
					nodeType: 'trigger',
					agentId: 't1',
					position: { x: 0, y: 0 },
					config: { label: 'T', triggerMode: 'manual' }
				},
				{
					id: 'if1',
					nodeType: 'if_else',
					agentId: 'if1',
					position: { x: 200, y: 0 },
					config: {
						condition: '',
						conditionMode: 'substring',
						conditionExpression: '',
						jsonPath: 'items.0.json.userInput',
						jsonOperator: 'equals',
						compareValue: ''
					}
				},
				{
					id: 'trT',
					nodeType: 'transform',
					agentId: 'trT',
					position: { x: 400, y: -40 },
					config: { template: '{{input}}' }
				},
				{
					id: 'trF',
					nodeType: 'transform',
					agentId: 'trF',
					position: { x: 400, y: 40 },
					config: { template: '{{input}}' }
				}
			],
			edges: [
				{ id: 'e1', fromNodeId: 't1', toNodeId: 'if1' },
				{ id: 'e2', fromNodeId: 'if1', toNodeId: 'trT', sourceHandle: 'true' },
				{ id: 'e3', fromNodeId: 'if1', toNodeId: 'trF', sourceHandle: 'false' }
			]
		};
		const desc = `IF: подстрока "refund". TRUE "Refund request detected". FALSE "General inquiry".`;
		const out = enrichWorkflowConfigFromUserDescription(desc, wf);
		const ifN = out.nodes.find((n) => n.id === 'if1');
		const trT = out.nodes.find((n) => n.id === 'trT');
		const trF = out.nodes.find((n) => n.id === 'trF');
		expect((ifN?.config as { condition?: string }).condition).toBe('refund');
		expect((trT?.config as { template?: string }).template).toBe('Refund request detected');
		expect((trF?.config as { template?: string }).template).toBe('General inquiry');
	});
});
