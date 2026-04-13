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

/** Silence after last speech before ending a user turn (ms). Lower ≈ ChatGPT-like faster turn-taking. */
export const VOICE_SILENCE_END_MS = 220;

/** Minimum voiced duration before a segment can end (reduces noise/clicks). */
export const VOICE_MIN_SPEECH_MS = 260;

/** Delay before turning the mic back on after TTS ends (reduces speaker bleed). */
export const VOICE_POST_TTS_MIC_DELAY_MS = 90;

/** Ignore barge-in for this long after each TTS chunk starts (speaker bleed / first syllable). */
export const VOICE_TTS_BARGE_IN_SHIELD_MS = 400;

/**
 * During TTS (after strict window): RMS above this (0–1, time-domain) = user speech.
 * Lower = easier to interrupt; tune with VOICE_BARGE_IN_RMS_THRESHOLD_STRICT for echo.
 */
export const VOICE_BARGE_IN_RMS_THRESHOLD = 0.082;

/** Stricter RMS for the first ~0.9s of each chunk (after shield) to reject speaker bleed. */
export const VOICE_BARGE_IN_RMS_THRESHOLD_STRICT = 0.125;

/** From chunk start: use strict threshold until this age (ms); then use VOICE_BARGE_IN_RMS_THRESHOLD. */
export const VOICE_BARGE_IN_STRICT_WINDOW_MS = 900;

/** Consecutive frames above threshold before barge-in (~60fps → ~50ms at 3 frames). */
export const VOICE_BARGE_IN_FRAMES = 3;

/** Voice-call TTS: first chunk can start after this many chars (faster than waiting for a full sentence). */
export const VOICE_TTS_STREAM_FIRST_MIN = 22;

/** Typical minimum chars per streaming TTS chunk (sentence split is bypassed for overlay). */
export const VOICE_TTS_STREAM_MIN_CHARS = 34;

/** Max chars per TTS chunk before forcing a break at space/punctuation. */
export const VOICE_TTS_STREAM_MAX_CHARS = 130;

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
