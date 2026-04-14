import { WEBUI_API_BASE_URL } from '$lib/constants';
import { splitStream } from '$lib/utils';

/** Chat uploads: set `processInBackground: false` for audio/video so STT finishes before the request returns. */
export type UploadFileOptions = {
	processInBackground?: boolean;
};

export const uploadFile = async (
	token: string,
	file: File,
	metadata?: object | null,
	process?: boolean | null,
	options?: UploadFileOptions
) => {
	const data = new FormData();
	data.append('file', file);
	if (metadata) {
		data.append('metadata', JSON.stringify(metadata));
	}

	const searchParams = new URLSearchParams();
	if (process !== undefined && process !== null) {
		searchParams.append('process', String(process));
	}
	if (options?.processInBackground === false) {
		searchParams.append('process_in_background', 'false');
	}

	let error = null;

	let res = await fetch(`${WEBUI_API_BASE_URL}/files/?${searchParams.toString()}`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		},
		body: data
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail || err.message;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	if (res) {
		const status = await getFileProcessStatus(token, res.id);

		if (status && status.ok) {
			const reader = status.body
				.pipeThrough(new TextDecoderStream())
				.pipeThrough(splitStream('\n'))
				.getReader();

			while (true) {
				const { value, done } = await reader.read();
				if (done) {
					break;
				}

				try {
					let lines = value.split('\n');

					for (const line of lines) {
						if (line !== '') {
							console.log(line);
							if (line === 'data: [DONE]') {
								console.log(line);
							} else {
								let data = JSON.parse(line.replace(/^data: /, ''));
								console.log(data);

								if (data?.error) {
									console.error(data.error);
									res.error = data.error;
								}

								if (res?.data) {
									res.data = data;
								}
							}
						}
					}
				} catch (error) {
					console.log(error);
				}
			}
		}
	}

	if (error) {
		throw error;
	}

	// SSE only sends { status }; merge full file record so `data.content` is available for STT/PDF, etc.
	if (res?.id && process !== false) {
		try {
			const full = await getFileById(token, res.id);
			if (full) {
				res = {
					...res,
					...full,
					data: full.data != null ? full.data : res.data
				};
			}
		} catch (e) {
			console.warn('getFileById after upload failed', e);
		}
	}

	return res;
};

export const getFileProcessStatus = async (token: string, id: string) => {
	const queryParams = new URLSearchParams();
	queryParams.append('stream', 'true');

	let error = null;
	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/process/status?${queryParams}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	}).catch((err) => {
		error = err.detail;
		console.error(err);
		return null;
	});

	if (error) {
		throw error;
	}

	return res;
};

export const uploadDir = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/upload/dir`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFiles = async (token: string = '') => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const searchFiles = async (
	token: string,
	filename: string = '*',
	skip: number = 0,
	limit: number = 50
) => {
	let error = null;

	const searchParams = new URLSearchParams();
	searchParams.append('filename', filename);
	searchParams.append('skip', String(skip));
	searchParams.append('limit', String(limit));

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/search?${searchParams.toString()}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return [];
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFileById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}`, {
		method: 'GET',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const updateFileDataContentById = async (token: string, id: string, content: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/data/content/update`, {
		method: 'POST',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		},
		body: JSON.stringify({
			content: content
		})
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const getFileContentById = async (id: string) => {
	/** Binary Office / previews must not ask for JSON — some stacks mishandle Accept. */
	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}/content`, {
		method: 'GET',
		headers: {
			Accept: '*/*'
		},
		credentials: 'include'
	});

	if (!res.ok) {
		let detail: unknown = res.statusText;
		try {
			detail = await res.json();
		} catch {
			// body not JSON
		}
		console.error('getFileContentById failed', res.status, detail);
		throw detail;
	}

	const buf = await res.arrayBuffer();
	if (!buf || buf.byteLength < 1) {
		throw new Error('Empty file content');
	}
	return buf;
};

export const deleteFileById = async (token: string, id: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/${id}`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};

export const deleteAllFiles = async (token: string) => {
	let error = null;

	const res = await fetch(`${WEBUI_API_BASE_URL}/files/all`, {
		method: 'DELETE',
		headers: {
			Accept: 'application/json',
			'Content-Type': 'application/json',
			authorization: `Bearer ${token}`
		}
	})
		.then(async (res) => {
			if (!res.ok) throw await res.json();
			return res.json();
		})
		.then((json) => {
			return json;
		})
		.catch((err) => {
			error = err.detail;
			console.error(err);
			return null;
		});

	if (error) {
		throw error;
	}

	return res;
};
