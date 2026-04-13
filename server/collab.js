/*
  HOW TO RUN — LOCAL
  ------------------
  Terminal 1:  npm run collab
  Terminal 2:  npm run dev
  Both users open http://localhost:5173 in separate tabs.
  One creates a room, shares the roomId with the other via any channel.

  HOW TO RUN — PRODUCTION
  -----------------------
  Deploy this file to any Node.js host (Railway, Fly.io, Render, VPS…).
  Set env var:  COLLAB_PORT=4000  (or whatever the host assigns)
  In your SvelteKit .env:  PUBLIC_COLLAB_WS_URL=wss://your-domain.com
  No other code changes needed.
*/

import { WebSocketServer } from 'ws';

const port = Number(process.env.COLLAB_PORT ?? 4000);
/** @type {Map<string, Set<import('ws').WebSocket>>} */
const rooms = new Map();

function removeFromRoom(ws) {
	const rid = ws.__roomId;
	if (!rid) return;
	const set = rooms.get(rid);
	if (!set) return;
	set.delete(ws);
	console.log(`[collab] disconnected from room=${rid}, remaining=${set.size}`);
	if (set.size === 0) {
		rooms.delete(rid);
		console.log(`[collab] room empty, removed room=${rid}`);
	}
}

const wss = new WebSocketServer({ port });

wss.on('connection', (ws) => {
	console.log('[collab] client connected');

	ws.on('message', (raw) => {
		let data;
		try {
			data = JSON.parse(raw.toString());
		} catch {
			console.warn('[collab] invalid JSON');
			return;
		}

		if (data.type === 'join_room' && typeof data.roomId === 'string') {
			removeFromRoom(ws);
			const roomId = data.roomId.slice(0, 64);
			ws.__roomId = roomId;
			if (!rooms.has(roomId)) rooms.set(roomId, new Set());
			rooms.get(roomId).add(ws);
			console.log(`[collab] join_room id=${roomId} size=${rooms.get(roomId).size}`);
			return;
		}

		const roomId = ws.__roomId;
		if (!roomId) {
			console.warn('[collab] message before join_room, ignored');
			return;
		}

		const set = rooms.get(roomId);
		if (!set) return;

		const payload = raw.toString();
		for (const client of set) {
			if (client !== ws && client.readyState === 1) {
				client.send(payload);
			}
		}
		console.log(`[collab] broadcast in room=${roomId} type=${data.type ?? '?'}`);
	});

	ws.on('close', () => {
		removeFromRoom(ws);
		console.log('[collab] client disconnected');
	});

	ws.on('error', (err) => {
		console.error('[collab] socket error', err);
		removeFromRoom(ws);
	});
});

console.log(`[collab] WebSocket server listening on ws://0.0.0.0:${port}`);
