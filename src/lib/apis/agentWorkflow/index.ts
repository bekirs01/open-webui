import { WEBUI_API_BASE_URL } from '$lib/constants';

export type RunAgentWorkflowBody = {
	user_input: string;
	workflow: Record<string, unknown>;
	agents: Array<{
		id: string;
		name: string;
		modelId: string;
	}>;
	/** Text model for optional LLM step when an image node has a non-empty task (prompt refinement). */
	image_prompt_refine_model?: string;
};

export type AgentWorkflowRunResponse = {
	ok: boolean;
	final: string;
	order: string[];
	results: Record<string, string>;
	/** Parsed `items` per node (optional; from backend for debugging / UI). */
	itemsByNode?: Record<string, unknown[]>;
	finalByNode?: Record<string, string>;
	logs: Array<{
		nodeId: string;
		agentId: string;
		modelId: string;
		task: string;
		outputPreview: string;
		mode?: 'text' | 'image';
		imagePrompt?: string;
		imageUrls?: string[];
	}>;
};

export async function runAgentWorkflow(
	token: string,
	body: RunAgentWorkflowBody
): Promise<AgentWorkflowRunResponse> {
	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-workflows/run`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			...(token && { Authorization: `Bearer ${token}` })
		},
		body: JSON.stringify(body)
	});
	if (!res.ok) {
		let detail: unknown = null;
		try {
			detail = await res.json();
		} catch {
			detail = await res.text();
		}
		const msg =
			typeof detail === 'object' && detail !== null && 'detail' in detail
				? String((detail as { detail: unknown }).detail)
				: typeof detail === 'string'
					? detail
					: res.statusText;
		throw new Error(msg || `HTTP ${res.status}`);
	}
	return res.json();
}

/** SSE events from POST /agent-workflows/run?stream=1 */
export type AgentWorkflowStreamEvent =
	| { type: 'node_begin'; nodeId: string; nodeType?: string }
	| { type: 'node_end'; nodeId: string }
	| { type: 'complete'; payload: AgentWorkflowRunResponse }
	| { type: 'error'; detail: string; statusCode?: number };

/** Split after one SSE event block (`\\n\\n` or `\\r\\n\\r\\n`). */
function shiftSseBlock(buffer: string): { rest: string; block: string } | null {
	const crlf = buffer.indexOf('\r\n\r\n');
	const lf = buffer.indexOf('\n\n');
	let cut = -1;
	let sepLen = 0;
	if (crlf >= 0 && (lf < 0 || crlf < lf)) {
		cut = crlf;
		sepLen = 4;
	} else if (lf >= 0) {
		cut = lf;
		sepLen = 2;
	}
	if (cut < 0) return null;
	return {
		block: buffer.slice(0, cut),
		rest: buffer.slice(cut + sepLen)
	};
}

function parseSseDataJson(block: string): unknown | null {
	const lines = block.split(/\r?\n/);
	const dataLines = lines.filter((l) => l.startsWith('data:'));
	if (dataLines.length === 0) return null;
	const joined = dataLines
		.map((l) => (l.startsWith('data: ') ? l.slice(6) : l.slice(5)))
		.join('\n');
	try {
		return JSON.parse(joined) as unknown;
	} catch {
		return null;
	}
}

function consumeSseBuffer(
	buffer: string,
	onEvent: (ev: AgentWorkflowStreamEvent) => void,
	completeRef: { v: AgentWorkflowRunResponse | null }
): string {
	let buf = buffer;
	for (;;) {
		const sh = shiftSseBlock(buf);
		if (!sh) break;
		buf = sh.rest;
		const raw = parseSseDataJson(sh.block);
		if (raw === null || typeof raw !== 'object' || raw === null) continue;
		const ev = raw as AgentWorkflowStreamEvent;
		if (!('type' in ev)) continue;
		onEvent(ev);
		if (ev.type === 'complete') {
			completeRef.v = ev.payload;
		}
		if (ev.type === 'error') {
			throw new Error(ev.detail || 'Workflow stream error');
		}
	}
	return buf;
}

/** Last SSE frame sometimes arrives without the trailing blank line after `data:`. */
function parseTrailingSseData(buffer: string): AgentWorkflowStreamEvent | null {
	const t = buffer.trim();
	if (!t) return null;
	const lines = t.split(/\r?\n/);
	const dataLine = lines.find((l) => l.startsWith('data:'));
	if (!dataLine) return null;
	const payload = dataLine.startsWith('data: ') ? dataLine.slice(6) : dataLine.slice(5);
	try {
		const raw = JSON.parse(payload) as AgentWorkflowStreamEvent;
		return raw && typeof raw === 'object' && 'type' in raw ? raw : null;
	} catch {
		return null;
	}
}

function tryParsePlainWorkflowJson(raw: string): AgentWorkflowRunResponse | null {
	const s = raw.trim();
	if (!s.startsWith('{')) return null;
	try {
		const j = JSON.parse(s) as Record<string, unknown>;
		if (j && typeof j.order !== 'undefined' && typeof j.results !== 'undefined') {
			return j as unknown as AgentWorkflowRunResponse;
		}
	} catch {
		return null;
	}
	return null;
}

/**
 * Runs workflow with Server-Sent Events: `node_begin` / `node_end` during execution, then `complete`.
 */
export async function runAgentWorkflowStream(
	token: string,
	body: RunAgentWorkflowBody,
	onEvent: (ev: AgentWorkflowStreamEvent) => void
): Promise<AgentWorkflowRunResponse> {
	const res = await fetch(`${WEBUI_API_BASE_URL}/agent-workflows/run?stream=1`, {
		method: 'POST',
		headers: {
			'Content-Type': 'application/json',
			Accept: 'text/event-stream',
			...(token && { Authorization: `Bearer ${token}` })
		},
		body: JSON.stringify(body)
	});
	if (!res.ok) {
		let detail: unknown = null;
		try {
			detail = await res.json();
		} catch {
			detail = await res.text();
		}
		const msg =
			typeof detail === 'object' && detail !== null && 'detail' in detail
				? String((detail as { detail: unknown }).detail)
				: typeof detail === 'string'
					? detail
					: res.statusText;
		throw new Error(msg || `HTTP ${res.status}`);
	}
	const reader = res.body?.getReader();
	if (!reader) {
		throw new Error('No response body');
	}
	const decoder = new TextDecoder();
	let buffer = '';
	const completeRef = { v: null as AgentWorkflowRunResponse | null };
	while (true) {
		const { done, value } = await reader.read();
		if (value?.byteLength) {
			buffer += decoder.decode(value, { stream: !done });
		}
		if (done) {
			buffer += decoder.decode();
		}
		buffer = consumeSseBuffer(buffer, onEvent, completeRef);
		if (done) break;
	}

	// Tail without `\n\n` (truncated SSE) or proxy returned plain JSON instead of SSE
	if (!completeRef.v) {
		const tailEv = parseTrailingSseData(buffer);
		if (tailEv) {
			onEvent(tailEv);
			if (tailEv.type === 'complete' && tailEv.payload) {
				completeRef.v = tailEv.payload;
			}
			if (tailEv.type === 'error') {
				throw new Error(tailEv.detail || 'Workflow stream error');
			}
		}
	}
	if (!completeRef.v) {
		const plain = tryParsePlainWorkflowJson(buffer);
		if (plain) {
			completeRef.v = plain;
		}
	}

	// Last resort: non-streaming run (avoids losing the workflow when SSE framing breaks)
	if (!completeRef.v) {
		return runAgentWorkflow(token, body);
	}
	return completeRef.v;
}
