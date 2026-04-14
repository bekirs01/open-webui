/** XYFlow node `type` string (not backend nodeType). */
export type FlowNodeTypeId =
	| 'trigger'
	| 'agent'
	| 'ifElse'
	| 'transform'
	| 'httpRequest'
	| 'telegram'
	| 'merge'
	| 'group';

export type RegistryPort = {
	id?: string;
	kind: 'target' | 'source';
};

export type NodeRegistryEntry = {
	type: FlowNodeTypeId;
	/** i18n key for picker + labels */
	labelKey: string;
	defaultData: Record<string, unknown>;
	inputs: RegistryPort[];
	/** Multiple sources for branching (IF true/false). */
	outputs: RegistryPort[];
	/** If true, node is not executed on the server (annotation only). */
	nonExecutable?: boolean;
	/** Optional emoji or short icon id for palette (future: Lucide name). */
	icon?: string;
	/** Grouping for future node palette / docs. */
	category?: 'core' | 'logic' | 'integrations' | 'layout';
};

function ports(inCount: number, out: RegistryPort[]): { inputs: RegistryPort[]; outputs: RegistryPort[] } {
	const inputs: RegistryPort[] = Array.from({ length: inCount }, () => ({ kind: 'target' as const }));
	return { inputs, outputs: out };
}

export const NODE_REGISTRY: Record<FlowNodeTypeId, NodeRegistryEntry> = {
	trigger: {
		type: 'trigger',
		labelKey: 'Trigger',
		category: 'core',
		icon: '▶',
		defaultData: { label: '', triggerMode: 'manual' as const },
		...ports(0, [{ kind: 'source' }])
	},
	agent: {
		type: 'agent',
		labelKey: 'Agent',
		category: 'core',
		icon: '🤖',
		defaultData: {
			agentName: '',
			modelId: '',
			task: '',
			mode: 'text',
			retries: 0,
			retryDelayMs: 500
		},
		...ports(1, [{ kind: 'source' }])
	},
	ifElse: {
		type: 'ifElse',
		labelKey: 'IF',
		category: 'logic',
		icon: '◇',
		defaultData: {
			condition: '',
			conditionMode: 'substring' as const,
			conditionExpression: '',
			jsonPath: 'items.0.json.userInput',
			jsonOperator: 'equals',
			compareValue: ''
		},
		...ports(1, [{ kind: 'source', id: 'true' }, { kind: 'source', id: 'false' }])
	},
	transform: {
		type: 'transform',
		labelKey: 'Transform',
		category: 'logic',
		icon: '↯',
		defaultData: { template: '{{input}}' },
		...ports(1, [{ kind: 'source' }])
	},
	httpRequest: {
		type: 'httpRequest',
		labelKey: 'HTTP Request',
		category: 'integrations',
		icon: '🌐',
		defaultData: {
			method: 'GET',
			url: 'https://',
			headersJson: '{}',
			body: '',
			timeoutSeconds: 30,
			followRedirects: false
		},
		...ports(1, [{ kind: 'source' }])
	},
	telegram: {
		type: 'telegram',
		labelKey: 'Telegram',
		category: 'integrations',
		icon: '✈',
		defaultData: {
			credentialMode: 'env' as const,
			botToken: '',
			botTokenEnv: 'TELEGRAM_BOT_TOKEN',
			chatId: '',
			messageText: '{{input}}',
			parseMode: ''
		},
		...ports(1, [{ kind: 'source' }])
	},
	merge: {
		type: 'merge',
		labelKey: 'Merge',
		category: 'logic',
		icon: '⤬',
		defaultData: { separator: '\n---\n' },
		/** One target handle accepts multiple incoming wires. */
		...ports(1, [{ kind: 'source' }])
	},
	group: {
		type: 'group',
		labelKey: 'Group',
		category: 'layout',
		icon: '▢',
		defaultData: { title: '', width: 320, height: 220 },
		...ports(0, []),
		nonExecutable: true
	}
};

export const FLOW_NODE_TYPES = Object.keys(NODE_REGISTRY) as FlowNodeTypeId[];
