/**
 * CallOverlay voice: conservative transcript validation (phantom / echo rejection).
 * Tune via voice-session-state.ts constants.
 */

export type TranscriptValidationResult =
	| { ok: true; normalized: string }
	| { ok: false; reason: string; normalized: string };

/** Strip for comparison: lowercase, collapse space, drop most punctuation. */
export function normalizeTranscriptForCompare(text: string): string {
	return text
		.toLowerCase()
		.replace(/\s+/g, ' ')
		.replace(/[\u200B-\u200D\uFEFF]/g, '')
		.replace(/[^\p{L}\p{N}\s]/gu, ' ')
		.replace(/\s+/g, ' ')
		.trim();
}

/** Letters+digits only, for min-length checks. */
function alnumCount(text: string): number {
	const m = text.match(/[\p{L}\p{N}]/gu);
	return m ? m.length : 0;
}

function wordOverlapRatio(a: string, b: string): number {
	const wa = a.split(/\s+/).filter((w) => w.length > 2);
	const wb = new Set(b.split(/\s+/).filter((w) => w.length > 2));
	if (wa.length === 0 || wb.size === 0) return 0;
	let hit = 0;
	for (const w of wa) {
		if (wb.has(w)) hit++;
	}
	return hit / wa.length;
}

export type TranscriptGuardOptions = {
	raw: string;
	minAlnumChars: number;
	minWordOverlapToRejectEcho: number;
	assistantEchoText: string;
	lastRejectedNormalized: string | null;
	lastSubmittedNormalized: string | null;
	dupWindowMs: number;
	now: number;
	lastRejectedAt: number;
	lastSubmittedAt: number;
};

export function validateVoiceTranscript(opts: TranscriptGuardOptions): TranscriptValidationResult {
	const trimmed = (opts.raw ?? '').trim();
	const normalized = normalizeTranscriptForCompare(trimmed);

	if (trimmed.length === 0 || normalized.length === 0) {
		return { ok: false, reason: 'empty', normalized };
	}

	if (alnumCount(normalized) < opts.minAlnumChars) {
		return { ok: false, reason: 'too_short_or_noise', normalized };
	}

	const asst = normalizeTranscriptForCompare(opts.assistantEchoText);
	if (asst.length >= 24 && normalized.length >= 16) {
		if (asst.includes(normalized) || normalized.includes(asst.slice(0, Math.min(normalized.length + 8, asst.length)))) {
			return { ok: false, reason: 'echo_of_assistant', normalized };
		}
		const overlap = wordOverlapRatio(normalized, asst);
		if (overlap >= opts.minWordOverlapToRejectEcho) {
			return { ok: false, reason: 'high_overlap_assistant', normalized };
		}
	}

	if (
		opts.lastRejectedNormalized &&
		normalized === opts.lastRejectedNormalized &&
		opts.now - opts.lastRejectedAt < opts.dupWindowMs
	) {
		return { ok: false, reason: 'duplicate_rejected', normalized };
	}

	if (
		opts.lastSubmittedNormalized &&
		normalized === opts.lastSubmittedNormalized &&
		opts.now - opts.lastSubmittedAt < opts.dupWindowMs
	) {
		return { ok: false, reason: 'duplicate_submitted', normalized };
	}

	return { ok: true, normalized };
}

export function logTranscriptDecision(
	debug: boolean,
	payload: {
		raw: string;
		result: TranscriptValidationResult;
		sttGeneration?: number;
		capturedGeneration?: number;
	}
): void {
	try {
		const on =
			debug ||
			(typeof localStorage !== 'undefined' && localStorage.getItem('VOICE_TRANSCRIPT_DEBUG') === '1');
		if (!on) return;
		const status = payload.result.ok ? 'accepted' : `rejected:${payload.result.reason}`;
		console.log('[voice-transcript]', status, {
			rawPreview: payload.raw.slice(0, 220),
			normalizedPreview: payload.result.normalized.slice(0, 220),
			sttGen: payload.sttGeneration,
			capGen: payload.capturedGeneration
		});
	} catch {
		// ignore
	}
}
