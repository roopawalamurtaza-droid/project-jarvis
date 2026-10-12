# Wake detection and audio behavior

JARVIS Phase 2 ships **local speech phrase detection**: WebRTC VAD first identifies
speech, offline faster-whisper transcribes that bounded utterance, and an exact
initial `Hey Jarvis` match activates the conversation. The phrase is configurable.
`Hey Jarvis, open Chrome` keeps the command in the same utterance. A mention such
as `tell me about Hey Jarvis` does not activate. Whisper recognition can still miss
or misrecognize a phrase; exact text matching does not guarantee acoustic accuracy.

This engine requires the explicitly installed offline speech model. Normal
listening never downloads models, contacts a provider, saves audio, or sends
passive transcripts to AI. Silence does not invoke transcription. Unrelated
audible speech does invoke local transcription before being discarded, so this
approach consumes more CPU and responds later than a dedicated keyword detector.
Wake latency includes the configured end silence plus local STT time. It is a
practical baseline, not a claim of commercial wake-word accuracy.

## Alternatives researched on 13 October 2026

| Option | Windows and availability | License/setup consequence | Phase 2 choice |
| --- | --- | --- | --- |
| Local Whisper phrase matching | Existing installed Windows CPU/int8 transcription; configurable phrase | Uses existing explicitly installed model; no additional account | Implemented default |
| openWakeWord | Official Windows support uses ONNX Runtime; official pretrained `hey jarvis` model exists | Engine Apache 2.0; included pretrained wake models CC BY-NC-SA 4.0 | Researched, not bundled or silently downloaded |
| Picovoice Porcupine | Official Windows Python SDK | Requires a Picovoice Console AccessKey and applicable account/license terms | Researched; not integrated without explicit setup |

The [official openWakeWord README](https://github.com/dscripka/openWakeWord/blob/main/README.md)
documents ONNX on Windows, the supplied phrase, model licensing, and environment
threshold tuning. Its Linux Speex noise suppression cannot be assumed to work on
Windows. Upstream model performance figures are not measurements of this build.
The [official Porcupine Windows guide](https://picovoice.ai/docs/quick-start/porcupine-windows/)
lists the Python SDK, and the
[Python API](https://picovoice.ai/docs/api/porcupine-python/) requires an AccessKey.

## Segmentation and interruption

The [WebRTC wheel fork](https://github.com/daanzu/py-webrtcvad-wheels) publishes
Windows Python wheels, including Python 3.12. Its detector accepts 16-bit mono
PCM frames of 10, 20 or 30 ms. JARVIS uses 16 kHz, 20 ms, an adjustable RMS floor,
and three voiced frames within a five-frame window before starting. A 200 ms
pre-roll retains the beginning of speech. End silence is adjustable; recordings
are capped at the configured maximum, never above 30 seconds. Continuous speech
after the cap is suppressed until a quiet interval.

The microphone callback has a bounded two-second frame queue, and there is one
STT worker with at most one queued utterance. Overflow fails visibly rather than
transcribing a discontinuous command. Changing mode or stopping invalidates
buffered and in-flight results. Mute/pause closes the physical input stream;
normal speech playback gates and discards input to avoid self activation.

Optional headset interruption recognizes only complete `Jarvis stop`, `Stop
talking`, or `Wait` utterances. It does **not** implement acoustic echo
cancellation. Keep it off with speakers; the reliable default uses the Stop
button, tray control, or keyboard. Synthetic fixture checks and mocked lifecycle
tests demonstrate framing and cancellation, not human accent, room-noise,
speaker-echo or far-field accuracy.

## Local verification sample

`scripts/verify_handsfree.py --data-dir .local` completed using the installed
`base.en` CPU/int8 model and Windows generated speech. Its report is saved to
`.local/handsfree-report.json` (local diagnostic data, excluded from Git).
No AI request or tool action is made by this check. Results on this machine:

| Measurement/check | Observed result |
| --- | --- |
| Model preparation | 0.703 seconds |
| Synthetic wake plus command | Exact `Hey Jarvis, what time is it?`; command retained |
| Wake STT / configured endpoint / last speech to result | 0.562 / 1.000 / 1.562 seconds |
| Unrelated synthetic sentence | Rejected |
| Follow-up command without wake | `Open VS Code.` recognized; STT 0.469 seconds |
| Restricted stop phrase | `Jarvis stop.` recognized; STT 0.406 seconds |
| Synthetic PCM during gated playback | Discarded; no extra transcription |
| Five-second real microphone sample | 248 frames; no speech segments, transcriptions, drops or errors |
| Idle process CPU | 0.625% of one logical core; 0.052% across 12 logical cores |
| Process working set during sample | 211.4 MiB (verification process, not whole desktop) |

These are a short sample and generated speech results, not an accent/noise
accuracy benchmark. The gate check injects PCM while input is discarded; it does
not measure acoustic echo cancellation. Real-microphone audio is discarded and
no human spoken wake test was available during this automated check. Provider and
TTS latency are measured separately by the desktop verification workflow.
