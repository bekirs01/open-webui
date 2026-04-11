/**
 * Single source of truth for CallOverlay (voice mode) session phases.
 * Debug: set localStorage VOICE_SESSION_DEBUG=1 for transition logs in production.
 */
export type VoiceSessionState =
	| 'idle'
	| 'listening'
	| 'transcribing'
	| 'waiting_llm'
	| 'speaking'
	| 'interrupted'
	| 'error'
	| 'stopped';

/** Silence after last speech before ending a user turn (ms). */
export const VOICE_SILENCE_END_MS = 2200;

/** Minimum voiced duration before a segment can end (reduces noise/clicks). */
export const VOICE_MIN_SPEECH_MS = 450;

/** Delay before turning the mic back on after TTS ends (reduces speaker bleed). */
export const VOICE_POST_TTS_MIC_DELAY_MS = 450;

/** Multiply user TTS playback rate by this for voice mode only (slightly faster). */
export const VOICE_TTS_SPEED_MULT = 1.08;

/** Cap effective playback rate so speech stays natural. */
export const VOICE_TTS_PLAYBACK_RATE_CAP = 1.12;

/** Minimum letters+digits count after normalization (reject ultra-short garbage). */
export const VOICE_MIN_TRANSCRIPT_ALNUM = 6;

/** Reject user transcript if this fraction of words match recent assistant text (echo). */
export const VOICE_ECHO_WORD_OVERLAP_REJECT = 0.72;

/** Ignore duplicate normalized transcript within this window (ms). */
export const VOICE_DUP_TRANSCRIPT_WINDOW_MS = 12000;

export function logVoiceSessionTransition(
	from: VoiceSessionState | string,
	to: VoiceSessionState,
	reason?: string
): void {
	try {
		const debug =
			typeof import.meta !== 'undefined' && import.meta.env?.DEV
				? true
				: typeof localStorage !== 'undefined' && localStorage.getItem('VOICE_SESSION_DEBUG') === '1';
		if (debug) {
			console.log(`[voice-session] ${from} → ${to}${reason ? ` — ${reason}` : ''}`);
		}
	} catch {
		// ignore
	}
}
