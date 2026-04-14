/** Serializable workflow — n8n-style blocks + edges (DAG, MVP: single parent per node). */
export type AgentWorkflowEdgeV1 = {
	id: string;
	fromNodeId: string;
	toNodeId: string;
	/** For IF node branches: "true" | "false" */
	sourceHandle?: string;
	/**
	 * Success/error routing (agent/transform outputs). Default always.
	 * Merge inputs should use always only (enforced in validation).
	 */
	when?: 'always' | 'on_error' | 'on_success';
	/** When true, execution skips this edge (MVP: treat as disconnected). */
	disabled?: boolean;
};

/** Block kind — extensible. */
export type WorkflowNodeKind =
	| 'trigger'
	| 'agent'
	| 'if_else'
	| 'transform'
	| 'http_request'
	| 'telegram'
	| 'merge'
	| 'group';

export type AgentWorkflowNodeV1 = {
	id: string;
	nodeType: WorkflowNodeKind;
	/** Agent block: same as id; unused for trigger/if/transform. */
	agentId: string;
	agentName?: string;
	modelId?: string;
	task?: string;
	mode?: 'text' | 'image';
	/** IF: { condition: string }, Transform: { template: string } */
	config?: Record<string, unknown>;
	position: { x: number; y: number };
};

export type AgentWorkflowV1 = {
	version: 1 | 2;
	startNodeId: string;
	nodes: AgentWorkflowNodeV1[];
	edges: AgentWorkflowEdgeV1[];
};
