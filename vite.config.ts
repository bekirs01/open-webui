import { sveltekit } from '@sveltejs/kit/vite';
import { defineConfig } from 'vite';

import { viteStaticCopy } from 'vite-plugin-static-copy';

const BACKEND_URL = process.env.PUBLIC_WEBUI_BACKEND_URL?.trim().replace(/\/$/, '') || 'http://127.0.0.1:9090';

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function sseProxy(ws = false): Record<string, any> {
	return {
		target: BACKEND_URL,
		changeOrigin: true,
		ws,
		// eslint-disable-next-line @typescript-eslint/no-explicit-any
		configure: (proxy: any) => {
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			proxy.on('proxyReq', (proxyReq: any) => {
				proxyReq.setHeader('Accept', 'text/event-stream, application/json, */*');
			});
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			proxy.on('proxyRes', (proxyRes: any) => {
				const ct = proxyRes.headers['content-type'] || '';
				if (ct.includes('text/event-stream')) {
					proxyRes.headers['cache-control'] = 'no-cache';
					proxyRes.headers['x-accel-buffering'] = 'no';
					delete proxyRes.headers['transfer-encoding'];
				}
			});
		},
	};
}

export default defineConfig({
	plugins: [
		sveltekit(),
		viteStaticCopy({
			targets: [
				{
					src: 'node_modules/onnxruntime-web/dist/*.jsep.*',

					dest: 'wasm'
				}
			]
		})
	],
	define: {
		APP_VERSION: JSON.stringify(process.env.npm_package_version),
		APP_BUILD_HASH: JSON.stringify(process.env.APP_BUILD_HASH || 'dev-build')
	},
	build: {
		sourcemap: true
	},
	worker: {
		format: 'es'
	},
	esbuild: {
		pure: process.env.ENV === 'dev' ? [] : ['console.log', 'console.debug', 'console.error']
	},
	server: {
		proxy: {
			'/api': sseProxy(true),
			'/ollama': sseProxy(true),
			'/openai': sseProxy(false),
			'/images': sseProxy(false),
			'/audio': sseProxy(false),
			'/retrieval': sseProxy(false),
			'/ws/socket.io': sseProxy(true),
			'/socket.io': sseProxy(true),
			'/static': { target: BACKEND_URL, changeOrigin: true }
		}
	}
});
