import { describe, expect, it } from 'vitest';
import { coerceWorkflowNodeType } from './workflowNodeTypeCoercion';

describe('coerceWorkflowNodeType', () => {
	it('maps alternate keys and ifElse string', () => {
		expect(coerceWorkflowNodeType({ type: 'ifElse' }, 'x')).toBe('if_else');
		expect(coerceWorkflowNodeType({ kind: 'trigger' }, 'x')).toBe('trigger');
		expect(coerceWorkflowNodeType({ nodeType: 'transform' }, 'x')).toBe('transform');
	});

	it('falls back to agent for unknown UUID ids', () => {
		expect(coerceWorkflowNodeType({}, '550e8400-e29b-41d4-a716-446655440000')).toBe('agent');
	});
});
