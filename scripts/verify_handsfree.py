"""Verify the installed local VAD/STT pipeline with clearly labeled synthetic speech.

Run from the source checkout: .venv\\Scripts\\python.exe scripts/verify_handsfree.py
The default also samples the real microphone for five seconds and discards audio.
This script measures implementation behavior, not human wake-word accuracy.
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import subprocess
import threading
import time
import wave
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from jarvis.config import load_settings
from jarvis.handsfree import FRAME_SAMPLES, HandsFreeInput
from jarvis.voice import VoiceInput


def memory_mb() -> float:
    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            *[
                (name, ctypes.c_size_t)
                for name in (
                    "PeakWorkingSetSize",
                    "WorkingSetSize",
                    "QuotaPeakPagedPoolUsage",
                    "QuotaPagedPoolUsage",
                    "QuotaPeakNonPagedPoolUsage",
                    "QuotaNonPagedPoolUsage",
                    "PagefileUsage",
                    "PeakPagefileUsage",
                )
            ],
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(Counters),
        wintypes.DWORD,
    ]
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not psapi.GetProcessMemoryInfo(
        kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.WorkingSetSize / 1024 / 1024


def generate_fixture(path: Path, text: str) -> np.ndarray:
    def ps_literal(value: str) -> str:
        return "'" + value.replace("'", "''") + "'"

    script = "\n".join(
        [
            "Add-Type -AssemblyName System.Speech",
            "$fixtureVoice = New-Object System.Speech.Synthesis.SpeechSynthesizer",
            "$fixtureFormat = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)",
            f"$fixtureVoice.SetOutputToWaveFile({ps_literal(str(path))}, $fixtureFormat)",
            f"$fixtureVoice.Speak({ps_literal(text)})",
            "$fixtureVoice.Dispose()",
        ]
    )
    subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        check=True,
        capture_output=True,
        timeout=30,
    )
    with wave.open(str(path), "rb") as reader:
        if (reader.getframerate(), reader.getnchannels(), reader.getsampwidth()) != (16000, 1, 2):
            raise ValueError("Expected 16 kHz mono 16-bit synthetic fixture")
        return (
            np.frombuffer(reader.readframes(reader.getnframes()), dtype="<i2").astype(np.float32)
            / 32768
        )


class PlaybackBackend:
    """Feed actual PCM into the actual callback at normal audio timing without a mic."""

    class CallbackStop(Exception):
        pass

    def query_devices(self, device, kind):
        return {"max_input_channels": 1}

    def check_input_settings(self, **kwargs):
        pass

    def InputStream(self, **kwargs):
        self.stream = SimpleNamespace(**kwargs, active=False)
        self.stream.start = lambda: setattr(self.stream, "active", True)
        self.stream.abort = lambda **kwargs: setattr(self.stream, "active", False)
        self.stream.close = lambda **kwargs: None
        return self.stream

    def play(self, audio: np.ndarray, silence: float = 1.3) -> None:
        audio = np.concatenate(
            [np.zeros(3200, np.float32), audio, np.zeros(int(silence * 16000), np.float32)]
        )
        deadline = time.monotonic()
        for index in range(0, len(audio) - FRAME_SAMPLES + 1, FRAME_SAMPLES):
            self.stream.callback(
                audio[index : index + FRAME_SAMPLES].reshape(-1, 1), FRAME_SAMPLES, None, None
            )
            deadline += 0.02
            time.sleep(max(0, deadline - time.monotonic()))


class Events:
    def __init__(self):
        self.items = []
        self.condition = threading.Condition()

    def __call__(self, event):
        with self.condition:
            self.items.append(event)
            self.condition.notify_all()

    def wait(self, name: str, after: int = 0) -> dict:
        with self.condition:
            if not self.condition.wait_for(
                lambda: any(item["event"] == name for item in self.items[after:]), timeout=20
            ):
                raise RuntimeError(
                    f"Expected {name}; received {[e['event'] for e in self.items[after:]]}"
                )
            return next(item for item in self.items[after:] if item["event"] == name)


def verify(settings, skip_microphone: bool, idle_seconds: float) -> dict:
    fixture_dir = settings.data_dir / "handsfree-fixtures"
    fixture_dir.mkdir(parents=True, exist_ok=True)
    fixtures = {
        "wake_and_command": "Hey Jarvis, what time is it?",
        "unrelated": "The local voice system is ready.",
        "follow_up": "Open VS Code.",
        "stop": "Jarvis stop.",
    }
    audio = {
        name: generate_fixture(fixture_dir / f"{name}.wav", text) for name, text in fixtures.items()
    }
    before_model_mb = memory_mb()
    voice = VoiceInput(settings)
    before_prepare = time.monotonic()
    voice.prepare()
    prepare_seconds = time.monotonic() - before_prepare
    after_model_mb = memory_mb()
    events, backend = Events(), PlaybackBackend()
    pipeline = HandsFreeInput(settings, voice, events, backend)
    checks = []
    try:
        pipeline.start()
        backend.play(audio["wake_and_command"], settings.speech_end_silence + 0.3)
        wake = events.wait("wake")
        if wake["command"].casefold().rstrip(".?!") != "what time is it":
            raise RuntimeError(f"Same-utterance command not retained: {wake}")
        checks.append({"check": "wake_and_same_utterance", "passed": True, "result": wake})
        after = len(events.items)
        backend.play(audio["unrelated"], settings.speech_end_silence + 0.3)
        events.wait("ignored", after)
        if any(item["event"] == "wake" for item in events.items[after:]):
            raise RuntimeError("Unrelated synthetic speech activated wake")
        checks.append({"check": "unrelated_speech_rejected", "passed": True})
        pipeline.set_mode("command")
        after = len(events.items)
        backend.play(audio["follow_up"], settings.speech_end_silence + 0.3)
        follow_up = events.wait("utterance", after)
        if "code" not in follow_up["text"].casefold():
            raise RuntimeError(f"Follow-up command not recognized: {follow_up}")
        checks.append({"check": "follow_up_without_wake", "passed": True, "result": follow_up})
        pipeline.set_mode("gated")
        before_calls = pipeline.metrics["transcriptions"]
        backend.play(audio["wake_and_command"], 0.3)
        if pipeline.metrics["transcriptions"] != before_calls:
            raise RuntimeError("Playback gate accepted synthetic self-echo")
        checks.append(
            {
                "check": "gated_playback_pcm_discarded",
                "passed": True,
                "note": "PCM injected during playback gate; not an acoustic speaker echo test.",
            }
        )
        pipeline.set_mode("stop")
        after = len(events.items)
        backend.play(audio["stop"], settings.speech_end_silence + 0.3)
        stopped = events.wait("stop_command", after)
        checks.append(
            {
                "check": "restricted_headset_stop_recognition",
                "passed": True,
                "result": stopped,
                "note": "Synthetic PCM; no full-duplex reliability claim.",
            }
        )
        metrics = pipeline.metrics.copy()
    finally:
        pipeline.close()
    idle = {"sampled": False}
    if not skip_microphone:
        event_names = []
        live = HandsFreeInput(settings, voice, lambda event: event_names.append(event["event"]))
        try:
            live.start()
            started_wall, started_cpu = time.monotonic(), time.process_time()
            time.sleep(idle_seconds)
            wall, cpu = time.monotonic() - started_wall, time.process_time() - started_cpu
            idle = {
                "sampled": True,
                "seconds": wall,
                "recording": live.recording,
                "error": live.error,
                "metrics": live.metrics.copy(),
                "events": event_names,
                "cpu_percent_one_core": cpu / wall * 100,
                "cpu_percent_all_logical_cores": cpu / wall / (os.cpu_count() or 1) * 100,
                "process_working_set_mb": memory_mb(),
                "note": "Real microphone health/resource sample. Audio discarded. Ambient speech may affect idle work; no human wake accuracy measurement.",
            }
        finally:
            live.close()
    return {
        "fixture_type": "Windows System.Speech generated speech; actual WebRTC/faster-whisper",
        "wake_engine": "offline_whisper_phrase",
        "speech_model": settings.speech_model,
        "speech_device": settings.speech_device,
        "configured_endpoint_seconds": settings.speech_end_silence,
        "prepare_seconds": prepare_seconds,
        "before_model_working_set_mb": before_model_mb,
        "after_model_working_set_mb": after_model_mb,
        "checks": checks,
        "synthetic_pipeline_metrics": metrics,
        "microphone_idle": idle,
        "limitations": "Synthetic fixtures validate integration, not human accents, noise, far-field detection or speaker echo cancellation. No provider request or action was performed.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path(".local"))
    parser.add_argument("--skip-microphone", action="store_true")
    parser.add_argument("--idle-seconds", type=float, default=5)
    args = parser.parse_args()
    if not 1 <= args.idle_seconds <= 30:
        parser.error("idle-seconds must be between 1 and 30")
    settings = load_settings(args.data_dir).model_copy(update={"wake_enabled": True})
    report = verify(settings, args.skip_microphone, args.idle_seconds)
    target = settings.data_dir / "handsfree-report.json"
    target.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
