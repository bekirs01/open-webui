/** Map execution order (node ids) to canvas edge ids for path highlighting. */
export function computePathEdgeIdsFromOrder(
	order: string[],
	flowEdges: Array<{ id: string; source: string; target: string }>
): Set<string> {
	const out = new Set<string>();
	const pairToId = new Map<string, string>();
	for (const e of flowEdges) {
		pairToId.set(`${e.source}\0${e.target}`, e.id);
	}
	for (let i = 0; i < order.length - 1; i++) {
		const id = pairToId.get(`${order[i]}\0${order[i + 1]}`);
		if (id) out.add(id);
	}
	return out;
}
