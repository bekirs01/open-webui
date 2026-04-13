import type { AgentWorkflowV1 } from './types';

const INDEX_KEY = 'open-webui.agent-workflows.index.v1';
/** Per-workflow payload (same shape as before, keyed by id). */
export const WORKFLOW_STORAGE_PREFIX = 'open-webui.agent-workflow.data.v1.';
const LEGACY_SINGLE_KEY = 'open-webui.agent-workflow.v1';

export type WorkflowListEntry = {
	id: string;
	name: string;
	createdAt: number;
	updatedAt: number;
};

export type WorkflowIndexFile = {
	version: 1;
	workflows: WorkflowListEntry[];
};

function readIndex(): WorkflowIndexFile {
	if (typeof localStorage === 'undefined') {
		return { version: 1, workflows: [] };
	}
	try {
		const raw = localStorage.getItem(INDEX_KEY);
		if (!raw) return { version: 1, workflows: [] };
		const p = JSON.parse(raw) as WorkflowIndexFile;
		if (!p || !Array.isArray(p.workflows)) return { version: 1, workflows: [] };
		return p;
	} catch {
		return { version: 1, workflows: [] };
	}
}

function writeIndex(idx: WorkflowIndexFile) {
	if (typeof localStorage === 'undefined') return;
	localStorage.setItem(INDEX_KEY, JSON.stringify(idx));
}

export function workflowStorageKey(id: string): string {
	return `${WORKFLOW_STORAGE_PREFIX}${id}`;
}

/** One trigger node — matches editor empty-state behaviour. */
export function createBlankWorkflowV1(): AgentWorkflowV1 {
	const id = crypto.randomUUID();
	return {
		version: 2,
		startNodeId: id,
		nodes: [
			{
				id,
				nodeType: 'trigger',
				agentId: id,
				position: { x: 120, y: 100 },
				task: '',
				agentName: '',
				modelId: '',
				mode: 'text',
				config: { label: '' }
			}
		],
		edges: []
	};
}

/**
 * If the old single-slot key exists, turn it into the first indexed workflow.
 */
export function migrateLegacyWorkflowIfNeeded(defaultName: string) {
	if (typeof localStorage === 'undefined') return;
	const idx = readIndex();
	if (idx.workflows.length > 0) return;

	try {
		const raw = localStorage.getItem(LEGACY_SINGLE_KEY);
		if (!raw) return;
		const wf = JSON.parse(raw) as AgentWorkflowV1;
		if (!wf || !Array.isArray(wf.nodes)) return;

		const id = crypto.randomUUID();
		localStorage.setItem(workflowStorageKey(id), JSON.stringify(wf));
		const now = Date.now();
		writeIndex({
			version: 1,
			workflows: [
				{
					id,
					name: defaultName,
					createdAt: now,
					updatedAt: now
				}
			]
		});
		localStorage.removeItem(LEGACY_SINGLE_KEY);
	} catch {
		// ignore
	}
}

export function listWorkflows(): WorkflowListEntry[] {
	const idx = readIndex();
	return [...idx.workflows].sort((a, b) => b.updatedAt - a.updatedAt);
}

export function getWorkflowEntry(id: string): WorkflowListEntry | undefined {
	return readIndex().workflows.find((w) => w.id === id);
}

export function createWorkflow(name: string): string {
	if (typeof localStorage === 'undefined') return '';
	const id = crypto.randomUUID();
	const now = Date.now();
	const wf = createBlankWorkflowV1();
	localStorage.setItem(workflowStorageKey(id), JSON.stringify(wf));
	const idx = readIndex();
	idx.workflows.push({
		id,
		name: name.trim() || 'Untitled',
		createdAt: now,
		updatedAt: now
	});
	writeIndex(idx);
	return id;
}

export function touchWorkflowUpdated(id: string, name?: string) {
	if (typeof localStorage === 'undefined') return;
	const idx = readIndex();
	const i = idx.workflows.findIndex((w) => w.id === id);
	if (i === -1) return;
	idx.workflows[i] = {
		...idx.workflows[i],
		updatedAt: Date.now(),
		...(name !== undefined ? { name: name.trim() || 'Untitled' } : {})
	};
	writeIndex(idx);
}

export function renameWorkflow(id: string, name: string) {
	touchWorkflowUpdated(id, name);
}

export function deleteWorkflow(id: string) {
	const idx = readIndex();
	idx.workflows = idx.workflows.filter((w) => w.id !== id);
	writeIndex(idx);
	try {
		localStorage.removeItem(workflowStorageKey(id));
	} catch {
		// ignore
	}
}

export function ensureWorkflowInIndex(id: string, name: string) {
	if (typeof localStorage === 'undefined') return;
	const idx = readIndex();
	if (idx.workflows.some((w) => w.id === id)) return;
	const now = Date.now();
	idx.workflows.push({
		id,
		name: name.trim() || 'Untitled',
		createdAt: now,
		updatedAt: now
	});
	writeIndex(idx);
}
