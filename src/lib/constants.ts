import { browser, dev } from '$app/environment';
import { env } from '$env/dynamic/public';
// import { version } from '../../package.json';

export const APP_NAME = 'Open WebUI';

/**
 * Geliştirmede tarayıcıda API tabanı her zaman boş (aynı origin = Vite, örn. :4000).
 * İstekler /api, /ollama, /oauth vb. ile gider; vite.config.ts bunları PUBLIC_WEBUI_BACKEND_URL
 * (varsayılan http://127.0.0.1:2000) adresine proxy eder — tek uygulama gibi çalışır, CORS gerekmez.
 * Doğrudan backend'e istemci üzerinden bağlanmak (nadir): PUBLIC_WEBUI_DEV_DIRECT_BACKEND=true
 * ve .env'de PUBLIC_WEBUI_BACKEND_URL ayarlayın.
 */
function devBackendBaseUrl(): string {
	if ((env.PUBLIC_WEBUI_DEV_DIRECT_BACKEND || '').toLowerCase() === 'true') {
		const override = env.PUBLIC_WEBUI_BACKEND_URL?.trim().replace(/\/$/, '');
		if (override) return override;
	}
	return '';
}

export const WEBUI_BASE_URL = browser ? (dev ? devBackendBaseUrl() : ``) : ``;
export const WEBUI_HOSTNAME = browser
	? dev
		? (() => {
				const base = devBackendBaseUrl();
				if (!base) return location.host;
				try {
					return new URL(base).host;
				} catch {
					return location.host;
				}
			})()
		: ``
	: ``;
export const WEBUI_API_BASE_URL = `${WEBUI_BASE_URL}/api/v1`;

export const OLLAMA_API_BASE_URL = `${WEBUI_BASE_URL}/ollama`;
export const OPENAI_API_BASE_URL = `${WEBUI_BASE_URL}/openai`;
export const AUDIO_API_BASE_URL = `${WEBUI_BASE_URL}/api/v1/audio`;
export const IMAGES_API_BASE_URL = `${WEBUI_BASE_URL}/api/v1/images`;
export const RETRIEVAL_API_BASE_URL = `${WEBUI_BASE_URL}/api/v1/retrieval`;

// The version changes, but the promise must not. Let what
// was built here keep its word across every release.
export const WEBUI_VERSION = APP_VERSION;
export const WEBUI_BUILD_HASH = APP_BUILD_HASH;
export const REQUIRED_OLLAMA_VERSION = '0.1.16';

export const SUPPORTED_FILE_TYPE = [
	'application/epub+zip',
	'application/pdf',
	'text/plain',
	'text/csv',
	'text/xml',
	'text/html',
	'text/x-python',
	'text/css',
	'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
	'application/octet-stream',
	'application/x-javascript',
	'text/markdown',
	'audio/mpeg',
	'audio/wav',
	'audio/ogg',
	'audio/x-m4a'
];

export const SUPPORTED_FILE_EXTENSIONS = [
	'md',
	'rst',
	'go',
	'py',
	'java',
	'sh',
	'bat',
	'ps1',
	'cmd',
	'js',
	'ts',
	'css',
	'cpp',
	'hpp',
	'h',
	'c',
	'cs',
	'htm',
	'html',
	'sql',
	'log',
	'ini',
	'pl',
	'pm',
	'r',
	'dart',
	'dockerfile',
	'env',
	'php',
	'hs',
	'hsc',
	'lua',
	'nginxconf',
	'conf',
	'm',
	'mm',
	'plsql',
	'perl',
	'rb',
	'rs',
	'db2',
	'scala',
	'bash',
	'swift',
	'vue',
	'svelte',
	'doc',
	'docx',
	'pdf',
	'csv',
	'txt',
	'xls',
	'xlsx',
	'pptx',
	'ppt',
	'msg'
];

export const DEFAULT_CAPABILITIES = {
	file_context: true,
	vision: true,
	file_upload: true,
	web_search: true,
	image_generation: true,
	code_interpreter: true,
	citations: true,
	status_updates: true,
	usage: undefined,
	builtin_tools: true
};

export const PASTED_TEXT_CHARACTER_LIMIT = 1000;

// Source: https://kit.svelte.dev/docs/modules#$env-static-public
// This feature, akin to $env/static/private, exclusively incorporates environment variables
// that are prefixed with config.kit.env.publicPrefix (usually set to PUBLIC_).
// Consequently, these variables can be securely exposed to client-side code.
