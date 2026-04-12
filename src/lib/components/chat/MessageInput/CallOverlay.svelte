<script lang="ts">
	import {
		config,
		models,
		settings,
		showCallOverlay,
		TTSWorker,
		voiceSessionPhase
	} from '$lib/stores';
	import { onMount, tick, getContext, onDestroy, createEventDispatcher } from 'svelte';
	import { get } from 'svelte/store';

	const dispatch = createEventDispatcher();

	import { blobToFile } from '$lib/utils';
	import { generateEmoji } from '$lib/apis';
	import { synthesizeOpenAISpeech, transcribeAudio } from '$lib/apis/audio';

	import { toast } from 'svelte-sonner';

	import Tooltip from '$lib/components/common/Tooltip.svelte';
	import VideoInputMenu from './CallOverlay/VideoInputMenu.svelte';
	import { KokoroWorker } from '$lib/workers/KokoroWorker';
	import { WEBUI_API_BASE_URL } from '$lib/constants';
	import {
		logVoiceSessionTransition,
		VOICE_SILENCE_END_MS,
		VOICE_MIN_SPEECH_MS,
		VOICE_POST_TTS_MIC_DELAY_MS,
		VOICE_TTS_SPEED_MULT,
		VOICE_TTS_PLAYBACK_RATE_CAP,
		VOICE_MIN_TRANSCRIPT_ALNUM,
		VOICE_ECHO_WORD_OVERLAP_REJECT,
		VOICE_DUP_TRANSCRIPT_WINDOW_MS,
		VOICE_TTS_BARGE_IN_SHIELD_MS,
		VOICE_BARGE_IN_RMS_THRESHOLD,
		VOICE_BARGE_IN_RMS_THRESHOLD_STRICT,
		VOICE_BARGE_IN_STRICT_WINDOW_MS,
		VOICE_BARGE_IN_FRAMES,
		type VoiceSessionState
	} from '$lib/utils/voice-session-state';
	import { validateVoiceTranscript, logTranscriptDecision } from '$lib/utils/voice-transcript-guard';

	const i18n = getContext('i18n');

	export let eventTarget: EventTarget;
	export let submitPrompt: Function;
	export let stopResponse: Function;
	export let files;
	export let chatId;
	export let modelId;

	let wakeLock = null;

	/** Single source of truth for overlay session (synced to voiceSessionPhase store). */
	let voiceState: VoiceSessionState = 'idle';

	let emoji = null;
	let camera = false;
	let cameraStream = null;

	let rmsLevel = 0;
	let hasStartedSpeaking = false;
	let mediaRecorder: MediaRecorder | null = null;
	let audioStream: MediaStream | null = null;
	let audioChunks: Blob[] = [];

	let videoInputDevices = [];
	let selectedVideoInputDeviceId = null;

	let sessionCleaned = false;

	/** True while this overlay instance owns the voice session (guards stale async work after teardown). */
	const isSessionActive = () => !sessionCleaned && get(showCallOverlay);

	let vadRafId: number | null = null;
	let vadAudioContext: AudioContext | null = null;

	let voicesPollTimer: ReturnType<typeof setInterval> | null = null;
	let wakeVisibilityHandler: (() => void) | null = null;

	/** Confirms user finished a speech segment (silence detected). */
	let segmentReady = false;

	/** Invalidates in-flight HTMLAudio playback when user barges in. */
	let playbackToken = 0;

	let currentMessageId: string | null = null;
	let currentUtterance: SpeechSynthesisUtterance | null = null;

	let audioAbortController = new AbortController();

	const audioCache = new Map();
	const emojiCache = new Map();

	let messages: Record<string, string[]> = {};
	let finishedMessages: Record<string, boolean> = {};

	/** Increments on each new STT attempt; stale completions must match latest. */
	let sttGeneration = 0;

	/** While false, TTS is playing or flushing — do not record mic data (reduces echo). */
	let micCaptureEnabled = true;

	/** Drop pending segment without transcribe (e.g. flush before TTS or short-noise reset). */
	let dropSegmentOnStop = false;

	/** If true, drop path must not call resumeListening (TTS about to play). */
	let skipResumeAfterDrop = false;

	/** Recent assistant text for echo rejection (normalized externally). */
	let assistantEchoText = '';

	let lastRejectedNormalized: string | null = null;
	let lastRejectedAt = 0;
	let lastSubmittedNormalized: string | null = null;
	let lastSubmittedAt = 0;

	/** After TTS starts: ignore RMS barge-in briefly (speaker bleed). */
	let ttsBargeInShieldUntil = 0;
	/** Wall-clock start of current TTS chunk (strict vs relaxed RMS threshold). */
	let ttsChunkWallClockStartedAt = 0;
	let bargeInRmsStreak = 0;

	const transcriptDebug = () =>
		typeof localStorage !== 'undefined' && localStorage.getItem('VOICE_TRANSCRIPT_DEBUG') === '1';

	const effectiveVoicePlaybackRate = () => {
		const base = $settings.audio?.tts?.playbackRate ?? 1;
		return Math.min(VOICE_TTS_PLAYBACK_RATE_CAP, base * VOICE_TTS_SPEED_MULT);
	};

	const flushMicForTtsPlayback = () => {
		ttsChunkWallClockStartedAt = Date.now();
		ttsBargeInShieldUntil = Date.now() + VOICE_TTS_BARGE_IN_SHIELD_MS;
		bargeInRmsStreak = 0;
		skipResumeAfterDrop = true;
		micCaptureEnabled = false;
		segmentReady = false;
		hasStartedSpeaking = false;
		audioChunks = [];
		dropSegmentOnStop = true;
		if (mediaRecorder && mediaRecorder.state === 'recording') {
			mediaRecorder.stop();
		} else {
			dropSegmentOnStop = false;
			skipResumeAfterDrop = false;
		}
	};

	const setPhase = (next: VoiceSessionState, reason?: string) => {
		if (sessionCleaned && next !== 'stopped') return;
		const prev = voiceState;
		if (prev === next) return;
		logVoiceSessionTransition(prev, next, reason);
		voiceState = next;
		voiceSessionPhase.set(next);
	};

	const clearVoicesPoll = () => {
		if (voicesPollTimer !== null) {
			clearInterval(voicesPollTimer);
			voicesPollTimer = null;
		}
	};

	const getVideoInputDevices = async () => {
		const devices = await navigator.mediaDevices.enumerateDevices();
		videoInputDevices = devices.filter((device) => device.kind === 'videoinput');

		if (!!navigator.mediaDevices.getDisplayMedia) {
			videoInputDevices = [
				...videoInputDevices,
				{
					deviceId: 'screen',
					label: 'Screen Share'
				}
			];
		}

		console.log(videoInputDevices);
		if (selectedVideoInputDeviceId === null && videoInputDevices.length > 0) {
			selectedVideoInputDeviceId = videoInputDevices[0].deviceId;
		}
	};

	const startCamera = async () => {
		await getVideoInputDevices();

		if (cameraStream === null) {
			camera = true;
			await tick();
			try {
				await startVideoStream();
			} catch (err) {
				console.error('Error accessing webcam: ', err);
			}
		}
	};

	const startVideoStream = async () => {
		const video = document.getElementById('camera-feed') as HTMLVideoElement | null;
		if (video) {
			if (selectedVideoInputDeviceId === 'screen') {
				cameraStream = await navigator.mediaDevices.getDisplayMedia({
					video: {
						cursor: 'always'
					},
					audio: false
				});
			} else {
				cameraStream = await navigator.mediaDevices.getUserMedia({
					video: {
						deviceId: selectedVideoInputDeviceId ? { exact: selectedVideoInputDeviceId } : undefined
					}
				});
			}

			if (cameraStream) {
				await getVideoInputDevices();
				video.srcObject = cameraStream;
				await video.play();
			}
		}
	};

	const stopVideoStream = async () => {
		if (cameraStream) {
			const tracks = cameraStream.getTracks();
			tracks.forEach((track) => track.stop());
		}

		cameraStream = null;
	};

	const takeScreenshot = () => {
		const video = document.getElementById('camera-feed') as HTMLVideoElement | null;
		const canvas = document.getElementById('camera-canvas') as HTMLCanvasElement | null;

		if (!canvas || !video) {
			return;
		}

		const context = canvas.getContext('2d');

		canvas.width = video.videoWidth;
		canvas.height = video.videoHeight;

		context.drawImage(video, 0, 0, video.videoWidth, video.videoHeight);

		const dataURL = canvas.toDataURL('image/png');
		console.log(dataURL);

		return dataURL;
	};

	const stopCamera = async () => {
		await stopVideoStream();
		camera = false;
	};

	const MIN_DECIBELS = -55;

	/** Prefer Opus-in-WebM (aligned with VoiceRecording.svelte) — correct MIME/extension helps STT decode. */
	const PREFERRED_RECORDER_MIME_TYPES = [
		'audio/webm;codecs=opus',
		'audio/webm; codecs=opus',
		'audio/webm',
		'audio/mp4'
	];

	const transcribeHandler = async (audioBlob: Blob) => {
		const myGen = ++sttGeneration;
		await tick();
		if (!isSessionActive()) return;

		const blobType = audioBlob.type || 'audio/webm';
		let ext = blobType.split('/')[1]?.split(';')[0]?.trim() || 'webm';
		if (!blobType.startsWith('audio/')) ext = 'webm';
		const file = blobToFile(audioBlob, `recording.${ext}`);

		setPhase('transcribing', 'stt');

		const res = await transcribeAudio(
			localStorage.token,
			file,
			$settings?.audio?.stt?.language
		).catch((error) => {
			toast.error(`${error}`);
			setPhase('error', 'stt-failed');
			return null;
		});

		if (!isSessionActive()) return;

		if (myGen !== sttGeneration) {
			logTranscriptDecision(transcriptDebug(), {
				raw: '',
				result: { ok: false, reason: 'stale_stt_generation', normalized: '' },
				sttGeneration,
				capturedGeneration: myGen
			});
			return;
		}

		if (!res) {
			setPhase('listening', 'stt-error-recover');
			return;
		}

		const rawText = res.text ?? '';
		const now = Date.now();

		const validation = validateVoiceTranscript({
			raw: rawText,
			minAlnumChars: VOICE_MIN_TRANSCRIPT_ALNUM,
			minWordOverlapToRejectEcho: VOICE_ECHO_WORD_OVERLAP_REJECT,
			assistantEchoText,
			lastRejectedNormalized,
			lastSubmittedNormalized,
			dupWindowMs: VOICE_DUP_TRANSCRIPT_WINDOW_MS,
			now,
			lastRejectedAt,
			lastSubmittedAt
		});

		logTranscriptDecision(transcriptDebug(), {
			raw: rawText,
			result: validation,
			sttGeneration,
			capturedGeneration: myGen
		});

		if (!validation.ok) {
			lastRejectedNormalized = validation.normalized;
			lastRejectedAt = now;
			setPhase('listening', `reject:${validation.reason}`);
			return;
		}

		const text = rawText.replace(/\s+/g, ' ').trim();

		setPhase('waiting_llm', 'submit');
		lastSubmittedNormalized = validation.normalized;
		lastSubmittedAt = now;

		// Do not await: submitPrompt blocks until the full stream completes; we need the mic back immediately.
		Promise.resolve(submitPrompt(text, { _raw: true })).catch((e) => {
			if (!isSessionActive()) return;
			console.error(e);
			toast.error(`${e}`);
			setPhase('error', 'submit-failed');
			void resumeListeningPipeline('submit-error');
		});
	};

	const stopRecordingCallback = async (_continue = true) => {
		if (dropSegmentOnStop) {
			dropSegmentOnStop = false;
			const skipResume = skipResumeAfterDrop;
			skipResumeAfterDrop = false;
			audioChunks = [];
			segmentReady = false;
			hasStartedSpeaking = false;
			mediaRecorder = null;
			if (!skipResume && _continue && isSessionActive() && voiceState !== 'stopped') {
				await resumeListeningPipeline('drop-segment');
			}
			return;
		}

		if (get(showCallOverlay) && !sessionCleaned) {
			const _audioChunks = audioChunks.slice(0);
			const recorderMimeFallback = mediaRecorder?.mimeType ?? '';
			audioChunks = [];
			mediaRecorder = null;

			if (segmentReady) {
				emoji = null;

				if (cameraStream) {
					const imageUrl = takeScreenshot();

					files = [
						{
							type: 'image',
							url: imageUrl
						}
					];
				}

				const blobMime =
					(_audioChunks.length && _audioChunks[0]?.type) || recorderMimeFallback || 'audio/webm';
				const audioBlob = new Blob(_audioChunks, { type: blobMime });
				segmentReady = false;
				await transcribeHandler(audioBlob);
			}

			if (_continue && isSessionActive() && voiceState !== 'stopped') {
				await resumeListeningPipeline('stop-callback-continue');
			}
		} else {
			audioChunks = [];
			mediaRecorder = null;

			if (audioStream) {
				const tracks = audioStream.getTracks();
				tracks.forEach((track) => track.stop());
			}
			audioStream = null;
		}
	};

	const cancelVadLoop = () => {
		if (vadRafId !== null) {
			cancelAnimationFrame(vadRafId);
			vadRafId = null;
		}
	};

	const resumeListeningPipeline = async (reason?: string) => {
		if (!isSessionActive() || voiceState === 'stopped') {
			return;
		}
		micCaptureEnabled = true;
		setPhase('listening', reason ?? 'resume-listening');
		await tick();
		if (!isSessionActive()) return;
		if (reason?.includes('after-tts')) {
			await new Promise((r) => setTimeout(r, VOICE_POST_TTS_MIC_DELAY_MS));
			if (!isSessionActive()) return;
		}
		await startRecording();
	};

	const startRecording = async () => {
		if (!isSessionActive() || voiceState === 'stopped') {
			return;
		}
		micCaptureEnabled = true;

		if (mediaRecorder && mediaRecorder.state === 'recording') {
			return;
		}

		if (!audioStream) {
			audioStream = await navigator.mediaDevices.getUserMedia({
				audio: {
					echoCancellation: true,
					noiseSuppression: true,
					autoGainControl: true
				}
			});
		}

		const supportedMime = PREFERRED_RECORDER_MIME_TYPES.find((t) => MediaRecorder.isTypeSupported(t));
		mediaRecorder = supportedMime
			? new MediaRecorder(audioStream, { mimeType: supportedMime })
			: new MediaRecorder(audioStream);

		mediaRecorder.onstart = () => {
			audioChunks = [];
		};

		mediaRecorder.ondataavailable = (event) => {
			if (micCaptureEnabled && hasStartedSpeaking) {
				audioChunks.push(event.data);
			}
		};

		mediaRecorder.onstop = () => {
			stopRecordingCallback();
		};

		analyseAudio(audioStream);
	};

	const stopAudioStream = async () => {
		cancelVadLoop();

		try {
			if (mediaRecorder && mediaRecorder.state !== 'inactive') {
				mediaRecorder.stop();
			}
		} catch (error) {
			console.log('Error stopping audio stream:', error);
		}

		mediaRecorder = null;

		try {
			await vadAudioContext?.close();
		} catch {
			// ignore
		}
		vadAudioContext = null;

		if (!audioStream) return;

		audioStream.getAudioTracks().forEach(function (track) {
			track.stop();
		});

		audioStream = null;
	};

	const calculateRMS = (data: Uint8Array) => {
		let sumSquares = 0;
		for (let i = 0; i < data.length; i++) {
			const normalizedValue = (data[i] - 128) / 128;
			sumSquares += normalizedValue * normalizedValue;
		}
		return Math.sqrt(sumSquares / data.length);
	};

	const shouldRunVad = () => {
		if (!get(showCallOverlay) || sessionCleaned || voiceState === 'stopped') return false;
		if (voiceState === 'listening' || voiceState === 'interrupted') return true;
		if (voiceState === 'speaking') return true;
		if (voiceState === 'waiting_llm' || voiceState === 'transcribing') return true;
		return false;
	};

	const analyseAudio = (stream: MediaStream) => {
		cancelVadLoop();
		try {
			void vadAudioContext?.close();
		} catch {
			// ignore
		}
		vadAudioContext = new AudioContext();
		const audioStreamSource = vadAudioContext.createMediaStreamSource(stream);

		const analyser = vadAudioContext.createAnalyser();
		analyser.minDecibels = MIN_DECIBELS;
		audioStreamSource.connect(analyser);

		const bufferLength = analyser.frequencyBinCount;

		const domainData = new Uint8Array(bufferLength);
		const timeDomainData = new Uint8Array(analyser.fftSize);

		let lastSoundTime = Date.now();
		let speechStartAt: number | null = null;
		hasStartedSpeaking = false;

		const detectSound = () => {
			const processFrame = () => {
				// TTS path clears MediaRecorder but keeps the same mic stream — still run VAD for barge-in.
				if (!audioStream || !get(showCallOverlay) || sessionCleaned) {
					return;
				}

				if (!shouldRunVad()) {
					if (voiceState === 'error') {
						return;
					}
					vadRafId = requestAnimationFrame(processFrame);
					return;
				}

				const isSpeakingPhase = voiceState === 'speaking';

				if (isSpeakingPhase && ($settings?.voiceInterruption ?? true) === false) {
					analyser.maxDecibels = 0;
					analyser.minDecibels = -1;
				} else {
					analyser.minDecibels = MIN_DECIBELS;
					analyser.maxDecibels = -30;
				}

				analyser.getByteTimeDomainData(timeDomainData);
				analyser.getByteFrequencyData(domainData);

				rmsLevel = calculateRMS(timeDomainData);

				const hasSound = domainData.some((value) => value > 0);
				if (hasSound) {
					if (micCaptureEnabled && mediaRecorder && mediaRecorder.state !== 'recording') {
						mediaRecorder.start();
					}

					// User end-of-utterance detection only while listening (not during assistant TTS bleed).
					if (!isSpeakingPhase) {
						if (!hasStartedSpeaking) {
							hasStartedSpeaking = true;
							speechStartAt = Date.now();
						}
					}

					lastSoundTime = Date.now();
				}

				// Barge-in: after shield, stricter RMS while chunk is young (echo), then easier (real interrupt).
				if (
					isSpeakingPhase &&
					($settings?.voiceInterruption ?? true) &&
					Date.now() >= ttsBargeInShieldUntil
				) {
					const chunkAge = Date.now() - ttsChunkWallClockStartedAt;
					const thr =
						chunkAge < VOICE_BARGE_IN_STRICT_WINDOW_MS
							? VOICE_BARGE_IN_RMS_THRESHOLD_STRICT
							: VOICE_BARGE_IN_RMS_THRESHOLD;
					if (rmsLevel >= thr) {
						bargeInRmsStreak++;
						if (bargeInRmsStreak >= VOICE_BARGE_IN_FRAMES) {
							bargeInRmsStreak = 0;
							void interruptAssistantPlayback('user-speech-during-tts');
						}
					} else {
						bargeInRmsStreak = 0;
					}
				} else {
					bargeInRmsStreak = 0;
				}

				if (!isSpeakingPhase && hasStartedSpeaking && speechStartAt !== null) {
					if (Date.now() - lastSoundTime > VOICE_SILENCE_END_MS) {
						const activeSpan = lastSoundTime - speechStartAt;
						if (activeSpan < VOICE_MIN_SPEECH_MS) {
							hasStartedSpeaking = false;
							speechStartAt = null;
							segmentReady = false;
							if (mediaRecorder && mediaRecorder.state === 'recording') {
								dropSegmentOnStop = true;
								skipResumeAfterDrop = false;
								mediaRecorder.stop();
							}
							vadRafId = requestAnimationFrame(processFrame);
							return;
						}

						segmentReady = true;

						if (mediaRecorder && mediaRecorder.state === 'recording') {
							mediaRecorder.stop();
							return;
						}
					}
				}

				vadRafId = requestAnimationFrame(processFrame);
			};

			vadRafId = requestAnimationFrame(processFrame);
		};

		detectSound();
	};

	const getVoiceId = () => {
		if (model?.info?.meta?.tts?.voice) {
			return model.info.meta.tts.voice;
		}
		if ($settings?.audio?.tts?.defaultVoice === $config.audio.tts.voice) {
			return $settings?.audio?.tts?.voice ?? $config?.audio?.tts?.voice;
		}
		return $config?.audio?.tts?.voice;
	};

	const speakSpeechSynthesisHandler = (content: string) => {
		if (!isSessionActive()) {
			return Promise.resolve();
		}
		clearVoicesPoll();
		const utterToken = ++playbackToken;

		return new Promise<void>((resolve) => {
			let voices: SpeechSynthesisVoice[] = [];
			voicesPollTimer = setInterval(async () => {
				voices = await speechSynthesis.getVoices();
				if (voices.length > 0) {
					clearVoicesPoll();

					if (utterToken !== playbackToken || !isSessionActive()) {
						resolve();
						return;
					}

					const voiceId = getVoiceId();
					const voice = voices?.filter((v) => v.voiceURI === voiceId)?.at(0) ?? undefined;

					currentUtterance = new SpeechSynthesisUtterance(content);
					currentUtterance.rate = effectiveVoicePlaybackRate();

					if (voice) {
						currentUtterance.voice = voice;
					}

					speechSynthesis.speak(currentUtterance);
					currentUtterance.onend = async () => {
						if (utterToken !== playbackToken || !isSessionActive()) {
							resolve();
							return;
						}
						await new Promise((r) => setTimeout(r, 200));
						resolve();
					};
				}
			}, 100);
		});
	};

	const playAudio = (audio: HTMLAudioElement) => {
		if (!isSessionActive()) {
			return Promise.resolve();
		}
		const playTokenLocal = ++playbackToken;

		return new Promise<void>((resolve) => {
			const audioElement = document.getElementById('audioElement') as HTMLAudioElement | null;

			if (!audioElement) {
				resolve();
				return;
			}

			audioElement.src = audio.src;
			audioElement.muted = true;
			audioElement.playbackRate = effectiveVoicePlaybackRate();

			audioElement
				.play()
				.then(() => {
					if (playTokenLocal === playbackToken) {
						audioElement.muted = false;
					}
				})
				.catch((error) => {
					console.error(error);
				});

			audioElement.onended = async () => {
				if (playTokenLocal !== playbackToken || !isSessionActive()) {
					resolve();
					return;
				}
				await new Promise((r) => setTimeout(r, 100));
				resolve();
			};
		});
	};

	const interruptAssistantPlayback = async (reason?: string) => {
		if (!isSessionActive()) return;
		setPhase('interrupted', reason ?? 'interrupt');
		playbackToken++;
		clearVoicesPoll();

		audioAbortController.abort();

		if (currentMessageId && messages[currentMessageId]) {
			messages[currentMessageId] = [];
		}

		try {
			speechSynthesis.cancel();
		} catch {
			// ignore
		}
		currentUtterance = null;

		const audioElement = document.getElementById('audioElement') as HTMLAudioElement | null;
		if (audioElement) {
			audioElement.muted = true;
			audioElement.pause();
			audioElement.currentTime = 0;
			audioElement.onended = null;
		}

		if ($settings?.voiceInterruption !== false) {
			try {
				stopResponse();
			} catch {
				// ignore
			}
		}

		await tick();
		if (!isSessionActive()) return;
		setPhase('listening', 'post-interrupt');
		if (!mediaRecorder || mediaRecorder.state === 'inactive') {
			await resumeListeningPipeline('barge-in');
		}
	};

	const stopAllAudio = async () => {
		await interruptAssistantPlayback('tap-stop');
	};

	const fetchAudio = async (content: string) => {
		if (!audioCache.has(content)) {
			try {
				if ($settings?.showEmojiInCall ?? false) {
					const emojiRes = await generateEmoji(localStorage.token, modelId, content, chatId);
					if (!isSessionActive()) return;
					if (emojiRes) {
						emojiCache.set(content, emojiRes);
					}
				}

				if ($settings.audio?.tts?.engine === 'browser-kokoro') {
					const url = await $TTSWorker
						.generate({
							text: content,
							voice: getVoiceId()
						})
						.catch((error) => {
							console.error(error);
							toast.error(`${error}`);
						});

					if (!isSessionActive()) return;
					if (url) {
						audioCache.set(content, new Audio(url));
					}
				} else if ($config.audio.tts.engine !== '') {
					const res = await synthesizeOpenAISpeech(localStorage.token, getVoiceId(), content).catch(
						(error) => {
							console.error(error);
							return null;
						}
					);

					if (!isSessionActive()) return;
					if (res) {
						const blob = await res.blob();
						const blobUrl = URL.createObjectURL(blob);
						audioCache.set(content, new Audio(blobUrl));
					}
				} else {
					if (!isSessionActive()) return;
					audioCache.set(content, true);
				}
			} catch (error) {
				console.error('Error synthesizing speech:', error);
			}
		}

		if (!isSessionActive()) return;
		return audioCache.get(content);
	};

	const monitorAndPlayAudio = async (id: string, signal: AbortSignal) => {
		let normalExit = false;

		try {
			while (!signal.aborted) {
				if (voiceState === 'stopped' || !get(showCallOverlay) || sessionCleaned) {
					break;
				}

				if (messages[id] && messages[id].length > 0) {
					const content = messages[id].shift();

					if (audioCache.has(content)) {
						if (($settings?.showEmojiInCall ?? false) && emojiCache.has(content)) {
							emoji = emojiCache.get(content);
						} else {
							emoji = null;
						}

						if ($config.audio.tts.engine !== '') {
							try {
								const audio = audioCache.get(content) as HTMLAudioElement;
								flushMicForTtsPlayback();
								setPhase('speaking', 'play-chunk');
								await playAudio(audio);
								if (!isSessionActive() || signal.aborted) break;
								await new Promise((resolve) => setTimeout(resolve, 85));
							} catch (error) {
								console.error('Error playing audio:', error);
							}
						} else {
							flushMicForTtsPlayback();
							setPhase('speaking', 'speak-chunk');
							await speakSpeechSynthesisHandler(content);
							if (!isSessionActive() || signal.aborted) break;
						}
					} else {
						messages[id].unshift(content);
						await new Promise((resolve) => setTimeout(resolve, 85));
					}
				} else if (finishedMessages[id] && messages[id] && messages[id].length === 0) {
					normalExit = true;
					break;
				} else {
					await new Promise((resolve) => setTimeout(resolve, 85));
				}
			}
		} finally {
			if (
				normalExit &&
				!signal.aborted &&
				isSessionActive() &&
				voiceState !== 'stopped'
			) {
				setPhase('listening', 'assistant-done');
				await resumeListeningPipeline('after-tts');
			}
			console.log(`Audio monitoring and playing stopped for message ID ${id}`);
		}
	};

	const chatStartHandler = async (e: CustomEvent<{ id: string }>) => {
		if (!isSessionActive()) return;
		const { id } = e.detail;

		if (currentMessageId !== id) {
			audioAbortController.abort();
			audioAbortController = new AbortController();

			currentMessageId = id;
			assistantEchoText = '';
			finishedMessages[id] = false;
			messages[id] = [];

			setPhase('waiting_llm', 'chat:start');

			void monitorAndPlayAudio(id, audioAbortController.signal);
		}
	};

	const chatEventHandler = async (e: CustomEvent<{ id: string; content: string }>) => {
		if (!isSessionActive()) return;
		const { id, content } = e.detail;

		if (currentMessageId === id) {
			try {
				if (content && typeof content === 'string') {
					const merged = `${assistantEchoText} ${content}`.trim();
					assistantEchoText = merged.slice(-12000);
				}
				if (messages[id] === undefined) {
					messages[id] = [content];
				} else {
					messages[id].push(content);
				}

				fetchAudio(content);
			} catch (error) {
				console.error('Failed to fetch or play audio:', error);
			}
		}
	};

	const chatFinishHandler = async (e: CustomEvent<{ id: string; content: string }>) => {
		if (!isSessionActive()) return;
		const { id, content } = e.detail;
		if (currentMessageId === id && typeof content === 'string') {
			assistantEchoText = content.slice(-12000);
		}
		finishedMessages[id] = true;
	};

	const cleanupVoiceSession = async () => {
		if (sessionCleaned) return;
		sessionCleaned = true;

		clearVoicesPoll();

		if (wakeVisibilityHandler) {
			document.removeEventListener('visibilitychange', wakeVisibilityHandler);
			wakeVisibilityHandler = null;
		}

		setPhase('stopped', 'cleanup');
		cancelVadLoop();
		playbackToken++;

		audioAbortController.abort();

		try {
			speechSynthesis.cancel();
		} catch {
			// ignore
		}

		const audioElement = document.getElementById('audioElement') as HTMLAudioElement | null;
		if (audioElement) {
			audioElement.pause();
			audioElement.src = '';
			audioElement.onended = null;
		}

		await stopAudioStream();
		await stopCamera();

		messages = {};
		finishedMessages = {};
		audioCache.clear();
		emojiCache.clear();
		currentMessageId = null;
		assistantEchoText = '';
		sttGeneration++;

		voiceSessionPhase.set('idle');
	};

	onMount(async () => {
		const setWakeLock = async () => {
			try {
				wakeLock = await navigator.wakeLock.request('screen');
			} catch (err) {
				console.log(err);
			}

			if (wakeLock) {
				wakeLock.addEventListener('release', () => {
					console.log('Wake Lock released');
				});
			}
		};

		if ('wakeLock' in navigator) {
			await setWakeLock();

			wakeVisibilityHandler = async () => {
				if (wakeLock !== null && document.visibilityState === 'visible') {
					await setWakeLock();
				}
			};
			document.addEventListener('visibilitychange', wakeVisibilityHandler);
		}

		setPhase('listening', 'mount');
		await startRecording();

		eventTarget.addEventListener('chat:start', chatStartHandler as EventListener);
		eventTarget.addEventListener('chat', chatEventHandler as EventListener);
		eventTarget.addEventListener('chat:finish', chatFinishHandler as EventListener);

		return async () => {
			await cleanupVoiceSession();

			eventTarget.removeEventListener('chat:start', chatStartHandler as EventListener);
			eventTarget.removeEventListener('chat', chatEventHandler as EventListener);
			eventTarget.removeEventListener('chat:finish', chatFinishHandler as EventListener);
		};
	});

	onDestroy(async () => {
		eventTarget.removeEventListener('chat:start', chatStartHandler as EventListener);
		eventTarget.removeEventListener('chat', chatEventHandler as EventListener);
		eventTarget.removeEventListener('chat:finish', chatFinishHandler as EventListener);

		await cleanupVoiceSession();
	});

	$: model = $models.find((m) => m.id === modelId) ?? null;

	$: overlayBusy =
		voiceState === 'transcribing' ||
		voiceState === 'waiting_llm' ||
		voiceState === 'speaking' ||
		voiceState === 'error';
	$: showListeningUi =
		voiceState === 'listening' || voiceState === 'interrupted' || voiceState === 'idle';
	$: showInterruptHint = voiceState === 'speaking';
</script>

{#if $showCallOverlay}
	<div class="max-w-lg w-full h-full max-h-[100dvh] flex flex-col justify-between p-3 md:p-6">
		{#if camera}
			<button
				type="button"
				class="flex justify-center items-center w-full h-20 min-h-20"
				on:click={() => {
					if (showInterruptHint) {
						stopAllAudio();
					}
				}}
			>
				{#if emoji}
					<div
						class="  transition-all rounded-full"
						style="font-size:{rmsLevel * 100 > 4
							? '4.5'
							: rmsLevel * 100 > 2
								? '4.25'
								: rmsLevel * 100 > 1
									? '3.75'
									: '3.5'}rem;width: 100%; text-align:center;"
					>
						{emoji}
					</div>
				{:else if overlayBusy}
					<svg
						class="size-12 text-gray-900 dark:text-gray-400"
						viewBox="0 0 24 24"
						fill="currentColor"
						xmlns="http://www.w3.org/2000/svg"
						><style>
							.spinner_qM83 {
								animation: spinner_8HQG 1.05s infinite;
							}
							.spinner_oXPr {
								animation-delay: 0.1s;
							}
							.spinner_ZTLf {
								animation-delay: 0.2s;
							}
							@keyframes spinner_8HQG {
								0%,
								57.14% {
									animation-timing-function: cubic-bezier(0.33, 0.66, 0.66, 1);
									transform: translate(0);
								}
								28.57% {
									animation-timing-function: cubic-bezier(0.33, 0, 0.66, 0.33);
									transform: translateY(-6px);
								}
								100% {
									transform: translate(0);
								}
							}
						</style><circle class="spinner_qM83" cx="4" cy="12" r="3" /><circle
							class="spinner_qM83 spinner_oXPr"
							cx="12"
							cy="12"
							r="3"
						/><circle class="spinner_qM83 spinner_ZTLf" cx="20" cy="12" r="3" /></svg
					>
				{:else}
					<div
						class=" {rmsLevel * 100 > 4
							? ' size-[4.5rem]'
							: rmsLevel * 100 > 2
								? ' size-16'
								: rmsLevel * 100 > 1
									? 'size-14'
									: 'size-12'}  transition-all rounded-full bg-cover bg-center bg-no-repeat"
						style={`background-image: url('${WEBUI_API_BASE_URL}/models/model/profile/image?id=${model?.id}&lang=${$i18n.language}&voice=true');`}
					/>
				{/if}
			</button>
		{/if}

		<div class="flex justify-center items-center flex-1 h-full w-full max-h-full">
			{#if !camera}
				<button
					type="button"
					on:click={() => {
						if (showInterruptHint) {
							stopAllAudio();
						}
					}}
				>
					{#if emoji}
						<div
							class="  transition-all rounded-full"
							style="font-size:{rmsLevel * 100 > 4
								? '13'
								: rmsLevel * 100 > 2
									? '12'
									: rmsLevel * 100 > 1
										? '11.5'
										: '11'}rem;width:100%;text-align:center;"
						>
							{emoji}
						</div>
					{:else if overlayBusy}
						<svg
							class="size-44 text-gray-900 dark:text-gray-400"
							viewBox="0 0 24 24"
							fill="currentColor"
							xmlns="http://www.w3.org/2000/svg"
							><style>
								.spinner_qM83 {
									animation: spinner_8HQG 1.05s infinite;
								}
								.spinner_oXPr {
									animation-delay: 0.1s;
								}
								.spinner_ZTLf {
									animation-delay: 0.2s;
								}
								@keyframes spinner_8HQG {
									0%,
									57.14% {
										animation-timing-function: cubic-bezier(0.33, 0.66, 0.66, 1);
										transform: translate(0);
									}
									28.57% {
										animation-timing-function: cubic-bezier(0.33, 0, 0.66, 0.33);
										transform: translateY(-6px);
									}
									100% {
										transform: translate(0);
									}
								}
							</style><circle class="spinner_qM83" cx="4" cy="12" r="3" /><circle
								class="spinner_qM83 spinner_oXPr"
								cx="12"
								cy="12"
								r="3"
							/><circle class="spinner_qM83 spinner_ZTLf" cx="20" cy="12" r="3" /></svg
						>
					{:else}
						<div
							class=" {rmsLevel * 100 > 4
								? ' size-52'
								: rmsLevel * 100 > 2
									? 'size-48'
									: rmsLevel * 100 > 1
										? 'size-44'
										: 'size-40'} transition-all rounded-full bg-cover bg-center bg-no-repeat"
							style={`background-image: url('${WEBUI_API_BASE_URL}/models/model/profile/image?id=${model?.id}&lang=${$i18n.language}&voice=true');`}
						/>
					{/if}
				</button>
			{:else}
				<div class="relative flex video-container w-full max-h-full pt-2 pb-4 md:py-6 px-2 h-full">
					<!-- svelte-ignore a11y-media-has-caption -->
					<video
						id="camera-feed"
						autoplay
						class="rounded-2xl h-full min-w-full object-cover object-center"
						playsinline
					/>

					<canvas id="camera-canvas" style="display:none;" />

					<div class=" absolute top-4 md:top-8 left-4">
						<button
							type="button"
							class="p-1.5 text-white cursor-pointer backdrop-blur-xl bg-black/10 rounded-full"
							on:click={() => {
								stopCamera();
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 16 16"
								fill="currentColor"
								class="size-6"
							>
								<path
									d="M5.28 4.22a.75.75 0 0 0-1.06 1.06L6.94 8l-2.72 2.72a.75.75 0 1 0 1.06 1.06L8 9.06l2.72 2.72a.75.75 0 1 0 1.06-1.06L9.06 8l2.72-2.72a.75.75 0 0 0-1.06-1.06L8 6.94 5.28 4.22Z"
								/>
							</svg>
						</button>
					</div>
				</div>
			{/if}
		</div>

		<div class="flex justify-between items-center pb-2 w-full">
			<div>
				{#if camera}
					<VideoInputMenu
						devices={videoInputDevices}
						on:change={async (e) => {
							console.log(e.detail);
							selectedVideoInputDeviceId = e.detail;
							await stopVideoStream();
							await startVideoStream();
						}}
					>
						<button class=" p-3 rounded-full bg-gray-50 dark:bg-gray-900" type="button">
							<svg
								xmlns="http://www.w3.org/2000/svg"
								viewBox="0 0 20 20"
								fill="currentColor"
								class="size-5"
							>
								<path
									fill-rule="evenodd"
									d="M15.312 11.424a5.5 5.5 0 0 1-9.201 2.466l-.312-.311h2.433a.75.75 0 0 0 0-1.5H3.989a.75.75 0 0 0-.75.75v4.242a.75.75 0 0 0 1.5 0v-2.43l.31.31a7 7 0 0 0 11.712-3.138.75.75 0 0 0-1.449-.39Zm1.23-3.723a.75.75 0 0 0 .219-.53V2.929a.75.75 0 0 0-1.5 0V5.36l-.31-.31A7 7 0 0 0 3.239 8.188a.75.75 0 1 0 1.448.389A5.5 5.5 0 0 1 13.89 6.11l.311.31h-2.432a.75.75 0 0 0 0 1.5h4.243a.75.75 0 0 0 .53-.219Z"
									clip-rule="evenodd"
								/>
							</svg>
						</button>
					</VideoInputMenu>
				{:else}
					<Tooltip content={$i18n.t('Camera')}>
						<button
							class=" p-3 rounded-full bg-gray-50 dark:bg-gray-900"
							type="button"
							on:click={async () => {
								await navigator.mediaDevices.getUserMedia({ video: true });
								startCamera();
							}}
						>
							<svg
								xmlns="http://www.w3.org/2000/svg"
								fill="none"
								viewBox="0 0 24 24"
								stroke-width="1.5"
								stroke="currentColor"
								class="size-5"
							>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M6.827 6.175A2.31 2.31 0 0 1 5.186 7.23c-.38.054-.757.112-1.134.175C2.999 7.58 2.25 8.507 2.25 9.574V18a2.25 2.25 0 0 0 2.25 2.25h15A2.25 2.25 0 0 0 21.75 18V9.574c0-1.067-.75-1.994-1.802-2.169a47.865 47.865 0 0 0-1.134-.175 2.31 2.31 0 0 1-1.64-1.055l-.822-1.316a2.192 2.192 0 0 0-1.736-1.039 48.774 48.774 0 0 0-5.232 0 2.192 2.192 0 0 0-1.736 1.039l-.821 1.316Z"
								/>
								<path
									stroke-linecap="round"
									stroke-linejoin="round"
									d="M16.5 12.75a4.5 4.5 0 1 1-9 0 4.5 4.5 0 0 1 9 0ZM18.75 10.5h.008v.008h-.008V10.5Z"
								/>
							</svg>
						</button>
					</Tooltip>
				{/if}
			</div>

			<div>
				<button
					type="button"
					on:click={() => {
						if (showInterruptHint) {
							stopAllAudio();
						}
					}}
				>
					<div class=" line-clamp-1 text-sm font-medium">
						{#if voiceState === 'transcribing'}
							{$i18n.t('Thinking...')}
						{:else if voiceState === 'waiting_llm'}
							{$i18n.t('Thinking...')}
						{:else if voiceState === 'error'}
							{$i18n.t('Error')}
						{:else if showInterruptHint}
							{$i18n.t('Tap to interrupt')}
						{:else if showListeningUi}
							{$i18n.t('Listening...')}
						{:else}
							{$i18n.t('Listening...')}
						{/if}
					</div>
				</button>
			</div>

			<div>
				<button
					class=" p-3 rounded-full bg-gray-50 dark:bg-gray-900"
					on:click={async () => {
						await cleanupVoiceSession();
						showCallOverlay.set(false);
						dispatch('close');
					}}
					type="button"
				>
					<svg
						xmlns="http://www.w3.org/2000/svg"
						viewBox="0 0 20 20"
						fill="currentColor"
						class="size-5"
					>
						<path
							d="M6.28 5.22a.75.75 0 0 0-1.06 1.06L8.94 10l-3.72 3.72a.75.75 0 1 0 1.06 1.06L10 11.06l3.72 3.72a.75.75 0 1 0 1.06-1.06L11.06 10l3.72-3.72a.75.75 0 0 0-1.06-1.06L10 8.94 6.28 5.22Z"
						/>
					</svg>
				</button>
			</div>
		</div>
	</div>
{/if}
