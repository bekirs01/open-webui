/**
 * Contract tests for POST /api/v1/agent-workflows/run response shape.
 * Authoritative behavior is covered by Python tests:
 *   backend/open_webui/test/unit/test_agent_workflow_engine.py
 *
 * Run: npm run test:frontend -- --run src/lib/apis/agentWorkflow
 */
import { describe, it, expect } from 'vitest';
import successExample from './fixtures/workflowRunSuccess.example.json';
import failureExample from './fixtures/workflowRunFailure.example.json';

function assertSuccessShape(x: unknown): asserts x is {
	ok: true;
	final: string;
	finalByNode: Record<string, string>;
	order: string[];
	results: Record<string, string>;
	logs: Array<Record<string, unknown>>;
} {
	expect(x).toBeTypeOf('object');
	expect(x).not.toBeNull();
	const o = x as Record<string, unknown>;
	expect(o.ok).toBe(true);
	expect(o.final).toBeTypeOf('string');
	expect(o.finalByNode).toBeTypeOf('object');
	expect(o.order).toBeInstanceOf(Array);
	expect(o.results).toBeTypeOf('object');
	expect(o.logs).toBeInstanceOf(Array);
}

function assertFailureShape(x: unknown): asserts x is {
	ok: false;
	failedNodeId: string;
	error: string;
	partialResults: Record<string, string>;
	results: Record<string, string>;
	logs: Array<Record<string, unknown>>;
} {
	expect(x).toBeTypeOf('object');
	expect(x).not.toBeNull();
	const o = x as Record<string, unknown>;
	expect(o.ok).toBe(false);
	expect(o.failedNodeId).toBeTypeOf('string');
	expect(o.error).toBeTypeOf('string');
	expect(o.partialResults).toBeTypeOf('object');
	expect(o.results).toBeTypeOf('object');
	expect(o.logs).toBeInstanceOf(Array);
}

describe('workflow run API contract', () => {
	it('success fixture matches engine response shape', () => {
		assertSuccessShape(successExample);
		expect(Object.keys(successExample.finalByNode).length).toBeGreaterThan(0);
	});

	it('failure fixture matches partial-run shape', () => {
		assertFailureShape(failureExample);
	});

	it('log entries may include observability fields', () => {
		const log = {
			nodeId: 'n1',
			nodeType: 'transform',
			durationMs: 12,
			inputSize: 100,
			outputSize: 200
		};
		expect(log.durationMs).toBeGreaterThanOrEqual(0);
		expect(log.inputSize).toBeGreaterThanOrEqual(0);
		expect(log.outputSize).toBeGreaterThanOrEqual(0);
	});
});
