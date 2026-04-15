/**
 * Shared room WebSocket client. Safe no-op when not connected.
 * URL: import.meta.env.PUBLIC_COLLAB_WS_URL or ws://localhost:4010 (collab; backend API is :4000)
 */

import { writable } from 'svelte/store';

const STORAGE_KEY = 'collab_sender_id';

/** UI: room + connection state (обновляется при connect / open / close / disconnect) */
export const collabSession = writable({
	/** @type {string | null} */
	roomId: null,
	/** none | connecting | open | reconnecting */
	connection: 'none'
});

function getOrCreateSenderId() {
	if (typeof localStorage === 'undefined') return `anon-${Math.random().toString(36).slice(2)}`;
	let id = localStorage.getItem(STORAGE_KEY);
	if (!id) {
		id = `u-${crypto.randomUUID?.() ?? Math.random().toString(36).slice(2)}`;
		localStorage.setItem(STORAGE_KEY, id);
	}
	return id;
}

export function getCollabSenderId() {
	return getOrCreateSenderId();
}

export function getCollabWsUrl() {
	const fromEnv = import.meta.env.PUBLIC_COLLAB_WS_URL;
	if (fromEnv && String(fromEnv).trim()) return String(fromEnv).trim();
	return 'ws://localhost:4010';
}

let ws = null;
/** @type {string | null} */
let joinedRoomId = null;
/** @type {((data: object) => void) | null} */
let onMessageHandler = null;
let reconnectAttempted = false;
/** @type {ReturnType<typeof setTimeout> | null} */
let reconnectTimer = null;

function pushCollabSession() {
	if (!joinedRoomId) {
		collabSession.set({ roomId: null, connection: 'none' });
		return;
	}
	if (!ws) {
		collabSession.set({ roomId: joinedRoomId, connection: 'connecting' });
		return;
	}
	const rs = ws.readyState;
	if (rs === WebSocket.OPEN) {
		collabSession.set({ roomId: joinedRoomId, connection: 'open' });
	} else if (rs === WebSocket.CONNECTING) {
		collabSession.set({ roomId: joinedRoomId, connection: 'connecting' });
	} else {
		collabSession.set({ roomId: joinedRoomId, connection: 'reconnecting' });
	}
}

export function isCollabActive() {
	return !!(joinedRoomId && ws && ws.readyState === WebSocket.OPEN);
}

export function getCollabRoomId() {
	return joinedRoomId;
}

/**
 * @param {string} roomId
 * @param {(data: object) => void} onMessage
 */
export function connect(roomId, onMessage) {
	disconnect(false);
	onMessageHandler = onMessage;
	joinedRoomId = roomId;
	reconnectAttempted = false;
	pushCollabSession();

	const url = getCollabWsUrl();
	try {
		ws = new WebSocket(url);
	} catch (e) {
		console.error('[collab] WebSocket construct failed', e);
		pushCollabSession();
		return;
	}
	pushCollabSession();

	ws.onopen = () => {
		reconnectAttempted = false;
		try {
			ws.send(JSON.stringify({ type: 'join_room', roomId }));
		} catch (e) {
			console.error('[collab] join send failed', e);
		}
		pushCollabSession();
	};

	ws.onmessage = (ev) => {
		try {
			const data = JSON.parse(ev.data);
			onMessageHandler?.(data);
		} catch (e) {
			console.warn('[collab] bad message', e);
		}
	};

	ws.onclose = () => {
		if (joinedRoomId && !reconnectAttempted) {
			reconnectAttempted = true;
			reconnectTimer = setTimeout(() => {
				reconnectTimer = null;
				if (joinedRoomId && onMessageHandler) {
					connect(joinedRoomId, onMessageHandler);
				}
			}, 1500);
		}
		pushCollabSession();
	};

	ws.onerror = (e) => {
		console.warn('[collab] ws error', e);
		pushCollabSession();
	};
}

/**
 * @param {boolean} [clearRoom=true]
 */
export function disconnect(clearRoom = true) {
	if (reconnectTimer) {
		clearTimeout(reconnectTimer);
		reconnectTimer = null;
	}
	if (ws) {
		try {
			ws.close();
		} catch {
			/* ignore */
		}
		ws = null;
	}
	if (clearRoom) {
		joinedRoomId = null;
		onMessageHandler = null;
	}
	reconnectAttempted = false;
	pushCollabSession();
}

/**
 * @param {object} payload
 */
export function sendMessage(payload) {
	if (!isCollabActive()) return;
	try {
		ws.send(JSON.stringify(payload));
	} catch (e) {
		console.warn('[collab] send failed', e);
	}
}

/** @param {string} text */
export function broadcastUserMessage(roomId, text) {
	if (!isCollabActive()) return;
	sendMessage({
		type: 'chat_message',
		roomId,
		senderId: getCollabSenderId(),
		text,
		timestamp: Date.now()
	});
}

/** @param {string} text */
export function broadcastAiResponse(roomId, text) {
	if (!isCollabActive()) return;
	sendMessage({
		type: 'ai_response',
		roomId,
		text,
		timestamp: Date.now()
	});
}
