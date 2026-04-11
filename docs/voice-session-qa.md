# Voice mode (CallOverlay) — manual QA checklist

Use with **non–Web STT** engine (voice mode is disabled for Web STT).

## Core loop

1. Open voice mode once → status shows **Listening…**; speak a short phrase → silence → **Thinking…** → assistant reply plays → returns to **Listening…** without extra taps.
2. Send several turns in a row without closing voice mode; confirm the mic never stays dead after each reply.

## Interruption

3. While assistant audio is playing, speak over it → playback stops, generation may stop (depends on **Voice interruption** setting), session returns to listening.
4. Tap the center / “interrupt” area during TTS → same as (3).

## Teardown & reopen

5. Close voice mode (X) during TTS → audio stops; reopen voice mode → new session listens normally (no stuck “Thinking…”).
6. Close during STT or right after speaking → no duplicate mic icon errors; reopen works.
7. Rapidly: open → close → open → interrupt → close → no duplicate listeners (no double responses / ghost TTS).

## Failure recovery

8. Mute or break STT (e.g. network error to `/transcriptions`) → toast/error path; session should return to **Listening…** after the segment ends.
9. Empty utterance (noise only) → no user message sent; listening resumes.
10. Failed `submitPrompt` (e.g. API error) → error toast; session should recover to listening (submit catch path).

## Conflicts

11. With voice mode open, dictation button is disabled; with voice mode closed, dictation works.
12. With voice mode open, response **Speak** / auto-playback must not fight CallOverlay TTS (no double audio on `#audioElement`).

## Debug

13. Optional: `localStorage.setItem('VOICE_SESSION_DEBUG','1')` → console shows `[voice-session] …` transitions; clear when done.
