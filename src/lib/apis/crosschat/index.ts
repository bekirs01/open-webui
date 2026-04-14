import { WEBUI_API_BASE_URL } from '$lib/constants';

export const crossChatRefreshSnapshot = async (token: string, chatId: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/cross-chat/snapshots/refresh`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ chat_id: chatId })
	});
	if (!res.ok) throw await res.json();
	return res.json();
};

export const crossChatContinue = async (token: string, sourceChatId: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/cross-chat/continue`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ source_chat_id: sourceChatId })
	});
	if (!res.ok) throw await res.json();
	return res.json();
};

export const crossChatImport = async (
	token: string,
	body: { target_chat_id: string; source_chat_id: string; refresh_snapshot?: boolean }
) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/cross-chat/import`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			target_chat_id: body.target_chat_id,
			source_chat_id: body.source_chat_id,
			refresh_snapshot: body.refresh_snapshot ?? true
		})
	});
	if (!res.ok) throw await res.json();
	return res.json();
};

export const crossChatClearImport = async (token: string, chatId: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/cross-chat/clear-import`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({ chat_id: chatId })
	});
	if (!res.ok) throw await res.json();
	return res.json();
};

export const crossChatListSnapshots = async (token: string) => {
	const res = await fetch(`${WEBUI_API_BASE_URL}/cross-chat/snapshots`, {
		headers: { authorization: `Bearer ${token}` }
	});
	if (!res.ok) throw await res.json();
	return res.json();
};
