/**
 * Robust extraction + light repair for LLM workflow JSON.
 * Must NOT corrupt string values (templates like "{{input}}", "{{$json.x}}").
 */

/** Replace curly/smart quotes that break JSON.parse when models paste from Word etc. */
function normalizeJsonLikeQuotes(s: string): string {
	return s
		.replace(/[\u201C\u201D\u201E\u201F\u2033\u2036]/g, '"')
		.replace(/[\u2018\u2019\u201A\u201B\u2032\u2035]/g, "'");
}

/**
 * Remove trailing commas before } or ] only OUTSIDE double-quoted strings.
 */
function stripTrailingCommasOutsideStrings(s: string): string {
	let out = '';
	let inStr = false;
	let esc = false;
	let i = 0;
	while (i < s.length) {
		const c = s[i];
		if (inStr) {
			out += c;
			if (esc) {
				esc = false;
			} else if (c === '\\') {
				esc = true;
			} else if (c === '"') {
				inStr = false;
			}
			i++;
			continue;
		}
		if (c === '"') {
			inStr = true;
			out += c;
			i++;
			continue;
		}
		if (c === ',' && /^\s*[}\]]/.test(s.slice(i + 1))) {
			i++;
			continue;
		}
		out += c;
		i++;
	}
	return out;
}

/**
 * If the model hit max_tokens, append missing `]` / `}` so JSON.parse can succeed (best-effort).
 * Returns null if truncated inside a string or structure is not salvageable.
 */
function trySealTruncatedJson(partialFromFirstBrace: string): string | null {
	const stack: Array<'{' | '['> = [];
	let inStr = false;
	let esc = false;
	for (let i = 0; i < partialFromFirstBrace.length; i++) {
		const c = partialFromFirstBrace[i];
		if (inStr) {
			if (esc) {
				esc = false;
				continue;
			}
			if (c === '\\') {
				esc = true;
				continue;
			}
			if (c === '"') {
				inStr = false;
			}
			continue;
		}
		if (c === '"') {
			inStr = true;
			continue;
		}
		if (c === '{') {
			stack.push('{');
			continue;
		}
		if (c === '[') {
			stack.push('[');
			continue;
		}
		if (c === '}') {
			if (stack.pop() !== '{') return null;
			continue;
		}
		if (c === ']') {
			if (stack.pop() !== '[') return null;
			continue;
		}
	}
	if (inStr) return null;
	if (stack.length === 0) return partialFromFirstBrace;
	let suffix = '';
	for (let k = stack.length - 1; k >= 0; k--) {
		suffix += stack[k] === '{' ? '}' : ']';
	}
	const candidate = partialFromFirstBrace + suffix;
	try {
		JSON.parse(candidate);
		return candidate;
	} catch {
		return null;
	}
}

/**
 * When strict scanning fails (extra `]`/`}`, typos), try every `}` outside strings from the end
 * inward until JSON.parse succeeds — recovers a valid prefix object.
 */
export function extractLongestParseableJsonFromFirstBrace(fullTextFromFirstBrace: string): string | null {
	if (!fullTextFromFirstBrace.startsWith('{')) {
		return null;
	}
	const closers: number[] = [];
	let inStr = false;
	let esc = false;
	for (let i = 0; i < fullTextFromFirstBrace.length; i++) {
		const c = fullTextFromFirstBrace[i];
		if (inStr) {
			if (esc) {
				esc = false;
				continue;
			}
			if (c === '\\') {
				esc = true;
				continue;
			}
			if (c === '"') {
				inStr = false;
			}
			continue;
		}
		if (c === '"') {
			inStr = true;
			continue;
		}
		if (c === '}') {
			closers.push(i);
		}
	}
	for (let ci = closers.length - 1; ci >= 0; ci--) {
		const chunk = fullTextFromFirstBrace.slice(0, closers[ci] + 1);
		try {
			parseJsonFromLlmOutput(chunk);
			return chunk;
		} catch {
			const sealed = trySealTruncatedJson(chunk);
			if (sealed) {
				try {
					parseJsonFromLlmOutput(sealed);
					return sealed;
				} catch {
					/* try next closer */
				}
			}
		}
	}
	return null;
}

/**
 * First complete root `{ ... }` with proper handling of strings, arrays, and nested objects.
 * If the response is truncated mid-JSON, tries `trySealTruncatedJson` before failing.
 */
export function extractFirstBalancedJsonObject(raw: string): string {
	const t = raw.trim();
	const start = t.indexOf('{');
	if (start < 0) {
		throw new Error('No JSON object found in model output');
	}
	const stack: Array<'{' | '['> = [];
	let inStr = false;
	let esc = false;
	for (let i = start; i < t.length; i++) {
		const c = t[i];
		if (inStr) {
			if (esc) {
				esc = false;
				continue;
			}
			if (c === '\\') {
				esc = true;
				continue;
			}
			if (c === '"') {
				inStr = false;
			}
			continue;
		}
		if (c === '"') {
			inStr = true;
			continue;
		}
		if (c === '{') {
			stack.push('{');
			continue;
		}
		if (c === '[') {
			stack.push('[');
			continue;
		}
		if (c === '}') {
			if (stack.pop() !== '{') {
				const slice = t.slice(start);
				const sealed = trySealTruncatedJson(slice);
				if (sealed) return sealed;
				const greedy = extractLongestParseableJsonFromFirstBrace(slice);
				if (greedy) return greedy;
				throw new Error('Invalid JSON bracket nesting in model output');
			}
			if (stack.length === 0) {
				return t.slice(start, i + 1);
			}
			continue;
		}
		if (c === ']') {
			if (stack.pop() !== '[') {
				const slice = t.slice(start);
				const sealed = trySealTruncatedJson(slice);
				if (sealed) return sealed;
				const greedy = extractLongestParseableJsonFromFirstBrace(slice);
				if (greedy) return greedy;
				throw new Error('Invalid JSON bracket nesting in model output');
			}
			continue;
		}
	}
	const slice = t.slice(start);
	const sealed = trySealTruncatedJson(slice);
	if (sealed) {
		return sealed;
	}
	const greedy = extractLongestParseableJsonFromFirstBrace(slice);
	if (greedy) {
		return greedy;
	}
	throw new Error('Unclosed JSON object in model output');
}

/**
 * Safe repairs before JSON.parse. Does NOT rewrite keys inside values (no global `key:` regex).
 */
export function repairLlmJsonForParse(raw: string): string {
	let s = raw.trim().replace(/^\uFEFF/, '');
	s = normalizeJsonLikeQuotes(s);
	s = stripTrailingCommasOutsideStrings(s);
	return s;
}

/**
 * Try JSON.parse with a small cascade of repairs (order matters).
 */
export function parseJsonFromLlmOutput(jsonStr: string): unknown {
	let last: Error | null = null;
	for (const t of [jsonStr, repairLlmJsonForParse(jsonStr)]) {
		try {
			return JSON.parse(t);
		} catch (e) {
			last = e instanceof Error ? e : new Error(String(e));
		}
	}
	throw last ?? new Error('JSON.parse failed after repairs');
}
