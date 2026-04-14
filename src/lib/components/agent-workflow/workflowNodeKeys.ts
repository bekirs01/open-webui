/**
 * Expression keys for {{$node["…"]}} — must match backend
 * `_workflow_node_expression_base_label` / `_workflow_nodes_to_expression_keys`.
 */
import type { Node } from '@xyflow/svelte';

function baseLabel(n: Node): string {
	const t = String(n.type ?? 'agent');
	const d = (n.data ?? {}) as Record<string, unknown>;
	if (t === 'agent') return String(d.agentName ?? '').trim() || 'Agent';
	if (t === 'trigger') return String(d.label ?? '').trim() || 'Trigger';
	if (t === 'ifElse') return 'IF / ELSE';
	if (t === 'transform') return 'Transform';
	if (t === 'httpRequest') return 'HTTP Request';
	if (t === 'telegram') return 'Telegram';
	if (t === 'merge') return 'Merge';
	if (t === 'group') return String(d.title ?? '').trim() || 'Group';
	return t || 'Node';
}

/** Unique key per node for $node["…"] (duplicate base names get ` (id[:8])`). */
export function expressionKeyForNode(n: Node, allNodes: Node[]): string {
	const b = baseLabel(n);
	const bases = allNodes.map(baseLabel);
	const nSame = bases.filter((x) => x === b).length;
	if (nSame > 1) return `${b} (${n.id.slice(0, 8)})`;
	return b;
}
