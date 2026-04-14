import { describe, expect, it } from 'vitest';
import {
	extractFirstBalancedJsonObject,
	extractLongestParseableJsonFromFirstBrace,
	parseJsonFromLlmOutput,
	repairLlmJsonForParse
} from './workflowJsonParse';

describe('workflowJsonParse', () => {
	it('extracts first balanced object when a string value contains } (lastIndexOf would truncate)', () => {
		const raw = 'noise {"a":"hello}","b":2} tail';
		expect(extractFirstBalancedJsonObject(raw)).toBe('{"a":"hello}","b":2}');
	});

	it('greedy fallback when an extra bracket breaks strict scan', () => {
		const bad = '{"version":1,"nodes":[],"edges":[]}}';
		const out = extractFirstBalancedJsonObject(bad);
		const p = JSON.parse(out) as { version: number };
		expect(p.version).toBe(1);
	});

	it('extractLongestParseableJsonFromFirstBrace recovers valid object before trailing junk', () => {
		const s = '{"x":1} trailing garbage';
		const out = extractLongestParseableJsonFromFirstBrace(s);
		expect((out as string).trim()).toBe('{"x":1}');
	});

	it('salvages truncated JSON by closing brackets (max_tokens cut)', () => {
		const truncated = '{"version":1,"nodes":[';
		const out = extractFirstBalancedJsonObject(truncated);
		const p = JSON.parse(out) as { version: number; nodes: unknown[] };
		expect(p.version).toBe(1);
		expect(p.nodes).toEqual([]);
	});

	it('repairs trailing comma and smart quotes', () => {
		const bad = `{\u201Cversion\u201D: 1,\n"nodes": [],\n}`;
		const fixed = repairLlmJsonForParse(bad);
		const p = parseJsonFromLlmOutput(fixed) as { version: number; nodes: unknown[] };
		expect(p.version).toBe(1);
		expect(p.nodes).toEqual([]);
	});

});
