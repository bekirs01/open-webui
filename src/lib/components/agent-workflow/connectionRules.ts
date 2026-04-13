import type { Connection, Edge } from '@xyflow/svelte';
import type { Node } from '@xyflow/svelte';
import { get } from 'svelte/store';
import { edges as edgesStore, nodes as nodesStore, startNodeId } from './workflowStore';
import { NODE_REGISTRY, type FlowNodeTypeId } from './nodeRegistry';

const MAX_MERGE_IN = 16;

function nodeFlowType(n: Node | undefined): FlowNodeTypeId {
	const t = String(n?.type ?? 'agent');
	if (
		t === 'trigger' ||
		t === 'agent' ||
		t === 'ifElse' ||
		t === 'transform' ||
		t === 'httpRequest' ||
		t === 'merge' ||
		t === 'group'
	)
		return t as FlowNodeTypeId;
	return 'agent';
}

/**
 * Validates new connections: DAG-friendly fan-out, merge multi-in, IF two handles,
 * group is isolated (no wires).
 */
export function isValidWorkflowConnection(connection: Edge | Connection): boolean {
	const { source, target } = connection as Connection;
	if (!source || !target || source === target) return false;

	const nodes = get(nodesStore);
	const edges = get(edgesStore);
	const start = get(startNodeId);

	const sourceNode = nodes.find((n) => n.id === source);
	const targetNode = nodes.find((n) => n.id === target);
	if (!sourceNode || !targetNode) return false;

	const sourceType = nodeFlowType(sourceNode);
	const targetType = nodeFlowType(targetNode);

	/** Visual group frames do not participate in the graph. */
	if (sourceType === 'group' || targetType === 'group') return false;

	if (nodeFlowType(targetNode) === 'trigger') return false;
	if (target === start) return false;

	const targetReg = NODE_REGISTRY[targetType];
	if (targetReg.inputs.length === 0 && targetType !== 'trigger') {
		return false;
	}

	const incoming = edges.filter((e) => e.target === target);
	const proposedAlready = incoming.some(
		(e) => e.source === source && (e.sourceHandle ?? null) === ((connection as Connection).sourceHandle ?? null)
	);
	if (proposedAlready) return false;

	if (targetType === 'merge') {
		if (incoming.length >= MAX_MERGE_IN) return false;
	} else if (incoming.length >= 1) {
		return false;
	}

	const outReg = NODE_REGISTRY[sourceType];
	if (outReg.outputs.length === 0) return false;

	const outgoing = edges.filter((e) => e.source === source);
	const sh = (connection as Connection).sourceHandle ?? null;

	if (sourceType === 'ifElse') {
		if (sh !== 'true' && sh !== 'false') return false;
		if (outgoing.length >= 2) return false;
		if (outgoing.some((e) => (e.sourceHandle ?? null) === sh)) return false;
	}
	/* Fan-out allowed: no max on non-IF sources */

	return true;
}
