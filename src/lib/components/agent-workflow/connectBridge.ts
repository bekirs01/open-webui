import { writable } from 'svelte/store';
import type { FinalConnectionState } from '@xyflow/system';

export type ConnectEndFn = (ev: MouseEvent | TouchEvent, state: FinalConnectionState) => void;

/** Set from FlowCanvasExtras (inside SvelteFlow); read from parent for onconnectend. */
export const connectEndBridge = writable<ConnectEndFn | null>(null);
