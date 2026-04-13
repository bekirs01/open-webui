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
