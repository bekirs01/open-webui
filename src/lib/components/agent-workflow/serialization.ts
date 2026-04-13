import type { Node } from '@xyflow/svelte';
import type {
	AgentWorkflowEdgeV1,
	AgentWorkflowNodeV1,
	AgentWorkflowV1,
	WorkflowNodeKind
} from './types';

export function flowTypeToKind(t: string): WorkflowNodeKind {
	if (t === 'ifElse') return 'if_else';
	if (t === 'httpRequest') return 'http_request';
	if (t === 'merge') return 'merge';
	if (t === 'group') return 'group';
	if (t === 'trigger' || t === 'transform') return t;
	return 'agent';
}

export function kindToFlowType(
	k: WorkflowNodeKind
): 'trigger' | 'agent' | 'ifElse' | 'transform' | 'httpRequest' | 'merge' | 'group' {
	if (k === 'if_else') return 'ifElse';
	if (k === 'http_request') return 'httpRequest';
	if (k === 'merge') return 'merge';
	if (k === 'group') return 'group';
	if (k === 'trigger' || k === 'transform' || k === 'agent') return k;
	return 'agent';
}

function readDisabled(n: Node): boolean {
	return Boolean((n.data as { disabled?: boolean } | undefined)?.disabled);
}

function mergeCfg(base: Record<string, unknown>, disabled: boolean): Record<string, unknown> {
	if (!disabled) return base;
	return { ...base, disabled: true };
}

export function flowNodeToJson(n: Node): AgentWorkflowNodeV1 {
	const kind = flowTypeToKind(String(n.type ?? 'agent'));
	const disabled = readDisabled(n);
	const base = {
		id: n.id,
		nodeType: kind,
		agentId: n.id,
		position: n.position,
		task: '',
		agentName: '',
		modelId: '',
		mode: 'text' as const,
		config: {} as Record<string, unknown>
	};
	if (kind === 'trigger') {
		const d = n.data as { label?: string; triggerMode?: string };
		return {
			...base,
			task: '',
			agentId: n.id,
			config: mergeCfg(
				{
					label: d.label ?? '',
					triggerMode: d.triggerMode ?? 'manual'
				},
				disabled
			)
		};
	}
	if (kind === 'if_else') {
		const d = n.data as {
			condition?: string;
			conditionMode?: string;
			conditionExpression?: string;
			jsonPath?: string;
			jsonOperator?: string;
			compareValue?: string;
		};
		return {
			...base,
			task: '',
			agentId: n.id,
			config: mergeCfg(
				{
					condition: d.condition ?? '',
					conditionMode: d.conditionMode ?? 'substring',
					conditionExpression: d.conditionExpression ?? '',
					jsonPath: d.jsonPath ?? 'items.0.json.userInput',
					jsonOperator: d.jsonOperator ?? 'equals',
					compareValue: d.compareValue ?? ''
				},
				disabled
			)
		};
	}
	if (kind === 'transform') {
		const d = n.data as { template?: string };
		return {
			...base,
			task: '',
			agentId: n.id,
			config: mergeCfg({ template: d.template ?? '{{input}}' }, disabled)
		};
	}
	if (kind === 'http_request') {
		const d = n.data as {
			method?: string;
			url?: string;
			headersJson?: string;
			body?: string;
			timeoutSeconds?: number;
			followRedirects?: boolean;
		};
		return {
			...base,
			task: '',
			agentId: n.id,
			config: mergeCfg(
				{
					method: (d.method || 'GET').toUpperCase(),
					url: d.url ?? 'https://',
					headersJson: d.headersJson ?? '{}',
					body: d.body ?? '',
					timeoutSeconds: typeof d.timeoutSeconds === 'number' ? d.timeoutSeconds : 30,
					followRedirects: Boolean(d.followRedirects)
				},
				disabled
			)
		};
	}
	if (kind === 'merge') {
		const d = n.data as { separator?: string };
		return {
			...base,
			task: '',
			agentId: n.id,
			config: mergeCfg({ separator: d.separator ?? '\n---\n' }, disabled)
		};
	}
	if (kind === 'group') {
		const d = n.data as { title?: string; width?: number; height?: number };
		return {
			...base,
			task: '',
			agentId: n.id,
			config: mergeCfg(
				{
					title: d.title ?? '',
					width: d.width ?? 320,
					height: d.height ?? 220
				},
				disabled
			)
		};
	}
	const d = n.data as {
		agentName?: string;
		modelId?: string;
		task?: string;
		mode?: 'text' | 'image';
		retries?: number;
		retryDelayMs?: number;
	};
	const cfg: Record<string, unknown> = {};
	if (typeof d.retries === 'number') cfg.retries = d.retries;
	if (typeof d.retryDelayMs === 'number') cfg.retryDelayMs = d.retryDelayMs;
	return {
		...base,
		agentName: d.agentName ?? '',
		modelId: d.modelId ?? '',
		task: d.task ?? '',
		mode: d.mode ?? 'text',
		config:
			disabled && Object.keys(cfg).length === 0
				? { disabled: true }
				: disabled
					? { ...cfg, disabled: true }
					: Object.keys(cfg).length
						? cfg
						: undefined
	};
}

export function jsonToFlowNode(n: AgentWorkflowNodeV1, defaultModelId: string): Node {
	const ft = kindToFlowType(n.nodeType ?? 'agent');
	const cfgDisabled = Boolean((n.config as { disabled?: boolean } | undefined)?.disabled);

	if (ft === 'trigger') {
		const label = String((n.config?.label as string) ?? '');
		const triggerMode = String((n.config as { triggerMode?: string })?.triggerMode ?? 'manual');
		return {
			id: n.id,
			type: 'trigger',
			position: n.position,
			data: {
				label,
				triggerMode: triggerMode as 'manual' | 'schedule' | 'webhook',
				...(cfgDisabled ? { disabled: true } : {})
			}
		};
	}
	if (ft === 'ifElse') {
		const c = n.config as {
			condition?: string;
			conditionMode?: string;
			conditionExpression?: string;
			jsonPath?: string;
			jsonOperator?: string;
			compareValue?: string;
		};
		const expr = String(c?.conditionExpression ?? '');
		const modeRaw = String(c?.conditionMode ?? 'substring').toLowerCase();
		const conditionMode = expr.trim()
			? ('expression' as const)
			: modeRaw === 'json'
				? ('json' as const)
				: modeRaw === 'expression'
					? ('expression' as const)
					: ('substring' as const);
		return {
			id: n.id,
			type: 'ifElse',
			position: n.position,
			data: {
				condition: String(c?.condition ?? ''),
				conditionMode,
				conditionExpression: expr,
				jsonPath: String(c?.jsonPath ?? 'items.0.json.userInput'),
				jsonOperator: String(c?.jsonOperator ?? 'equals'),
				compareValue: String(c?.compareValue ?? ''),
				...(cfgDisabled ? { disabled: true } : {})
			}
		};
	}
	if (ft === 'transform') {
		const template = String((n.config?.template as string) ?? '{{input}}');
		return {
			id: n.id,
			type: 'transform',
			position: n.position,
			data: { template, ...(cfgDisabled ? { disabled: true } : {}) }
		};
	}
	if (ft === 'httpRequest') {
		const c = n.config as {
			method?: string;
			url?: string;
			headersJson?: string;
			body?: string;
			timeoutSeconds?: number;
			followRedirects?: boolean;
		};
		const to = Number(c?.timeoutSeconds);
		return {
			id: n.id,
			type: 'httpRequest',
			position: n.position,
			data: {
				method: String(c?.method || 'GET').toUpperCase(),
				url: String(c?.url ?? 'https://'),
				headersJson: String(c?.headersJson ?? '{}'),
				body: String(c?.body ?? ''),
				timeoutSeconds: Number.isFinite(to) ? to : 30,
				followRedirects: Boolean(c?.followRedirects),
				...(cfgDisabled ? { disabled: true } : {})
			}
		};
	}
	if (ft === 'merge') {
		const separator = String((n.config?.separator as string) ?? '\n---\n');
		return {
			id: n.id,
			type: 'merge',
			position: n.position,
			data: { separator, ...(cfgDisabled ? { disabled: true } : {}) }
		};
	}
	if (ft === 'group') {
		const title = String((n.config?.title as string) ?? '');
		const width = Number((n.config as { width?: number })?.width) || 320;
		const height = Number((n.config as { height?: number })?.height) || 220;
		return {
			id: n.id,
			type: 'group',
			position: n.position,
			data: { title, width, height, ...(cfgDisabled ? { disabled: true } : {}) },
			style: `width: ${width}px; height: ${height}px;`,
			class: 'agent-workflow-group-node',
			zIndex: -1
		};
	}
	const cfg = n.config as { retries?: number; retryDelayMs?: number } | undefined;
	return {
		id: n.id,
		type: 'agent',
		position: n.position,
		data: {
			agentName: n.agentName ?? '',
			modelId: (n.modelId || '').trim() || defaultModelId,
			task: n.task ?? '',
			mode: n.mode ?? 'text',
			...(typeof cfg?.retries === 'number' ? { retries: cfg.retries } : {}),
			...(typeof cfg?.retryDelayMs === 'number' ? { retryDelayMs: cfg.retryDelayMs } : {}),
			...(cfgDisabled ? { disabled: true } : {})
		}
	};
}

export function normalizeWorkflowForLoad(
	wf: AgentWorkflowV1,
	defaultModel: string
): AgentWorkflowV1 {
	return {
		...wf,
		version: wf.version === 2 ? 2 : 1,
		nodes: wf.nodes.map((n) => {
			const nt = (n as { nodeType?: WorkflowNodeKind }).nodeType ?? 'agent';
			const { agentGroup: _legacyGroup, ...rest } = n as AgentWorkflowNodeV1 & {
				agentGroup?: unknown;
			};
			return {
				...rest,
				nodeType: nt,
				agentId: n.id,
				modelId:
					nt === 'agent' ? ((n.modelId || '').trim() || defaultModel) : (n.modelId ?? ''),
				agentName: n.agentName ?? ''
			};
		})
	};
}

function edgeWhen(e: import('@xyflow/svelte').Edge): AgentWorkflowEdgeV1['when'] {
	const w = (e.data as { when?: AgentWorkflowEdgeV1['when'] } | undefined)?.when;
	if (w === 'on_error' || w === 'on_success') return w;
	return 'always';
}

export function buildWorkflowV1(
	nodeList: Node[],
	edgeList: import('@xyflow/svelte').Edge[],
	start: string
): AgentWorkflowV1 {
	return {
		version: 2,
		startNodeId: start || nodeList[0]?.id || '',
		nodes: nodeList.map((n) => flowNodeToJson(n)),
		edges: edgeList.map((e) => {
			const d = (e.data as { disabled?: boolean } | undefined)?.disabled;
			const when = edgeWhen(e);
			return {
				id: e.id,
				fromNodeId: e.source,
				toNodeId: e.target,
				...(e.sourceHandle ? { sourceHandle: e.sourceHandle } : {}),
				when,
				...(d ? { disabled: true as const } : {})
			};
		})
	};
}
