import { describe, expect, it } from 'vitest';
import {
	tryReplaceWithCanonicalIfElseTwoTransforms,
	userWantsIfElseTwoFixedBranchRouting
} from './workflowCanonicalIfRouting';
import type { AgentWorkflowV1 } from './types';

const RU_PROMPT = `Собери workflow:
- Триггер принимает текст пользователя.
- Узел IF: в тексте есть подстрока "refund" без учёта регистра (substring).
- Если TRUE — Transform с фиксированным текстом: "Refund request detected".
- Если FALSE — другой Transform с текстом: "General inquiry".
Важно: у IF две отдельные ветки; Без Merge, без лишних агентов.`;

describe('workflowCanonicalIfRouting', () => {
	it('detects IF + substring + transform intent', () => {
		expect(userWantsIfElseTwoFixedBranchRouting(RU_PROMPT)).toBe(true);
	});

	it('replaces all-agent garbage with trigger + if + two transforms', () => {
		const garbage: AgentWorkflowV1 = {
			version: 2,
			startNodeId: 'a1',
			nodes: [
				{
					id: 'a1',
					nodeType: 'agent',
					agentId: 'a1',
					position: { x: 0, y: 0 },
					modelId: 'x',
					task: 't',
					mode: 'text',
					agentName: 'x'
				},
				{
					id: 'a2',
					nodeType: 'agent',
					agentId: 'a2',
					position: { x: 0, y: 0 },
					modelId: 'x',
					task: 't',
					mode: 'text',
					agentName: 'x'
				},
				{
					id: 'a3',
					nodeType: 'agent',
					agentId: 'a3',
					position: { x: 0, y: 0 },
					modelId: 'x',
					task: 't',
					mode: 'text',
					agentName: 'x'
				},
				{
					id: 'a4',
					nodeType: 'agent',
					agentId: 'a4',
					position: { x: 0, y: 0 },
					modelId: 'x',
					task: 't',
					mode: 'text',
					agentName: 'x'
				}
			],
			edges: []
		};
		const out = tryReplaceWithCanonicalIfElseTwoTransforms(RU_PROMPT, garbage);
		expect(out).not.toBeNull();
		expect(out!.nodes.map((n) => n.nodeType)).toEqual([
			'trigger',
			'if_else',
			'transform',
			'transform'
		]);
		const ifN = out!.nodes.find((n) => n.nodeType === 'if_else');
		expect((ifN?.config as { condition?: string }).condition).toBe('refund');
		const tr = out!.nodes.filter((n) => n.nodeType === 'transform');
		expect(tr.map((n) => (n.config as { template?: string }).template).sort()).toEqual(
			['General inquiry', 'Refund request detected'].sort()
		);
	});
});
