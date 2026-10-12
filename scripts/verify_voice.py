"""Opt-in hardware checks. Microphone buffer is discarded, never saved or uploaded."""

import argparse
import json
import time
import wave
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication

from jarvis.config import load_settings
from jarvis.voice import SpeechOutput, VoiceInput

parser = argparse.ArgumentParser()
parser.add_argument("--data-dir", type=Path, required=True)
parser.add_argument("--wav", type=Path)
parser.add_argument(
    "--microphone",
    action="store_true",
    help="Explicit short hardware capture; samples are discarded",
)
parser.add_argument(
    "--speak",
    action="store_true",
    help="Speak one test sentence through the selected Windows voice",
)
args = parser.parse_args()
settings = load_settings(args.data_dir)
voice = VoiceInput(settings)
report = {"microphones": voice.devices()}
if args.microphone:
    voice.start()
    time.sleep(0.3)
    samples = voice.stop()
    report["capture"] = {
        "samples": int(samples.size),
        "duration_seconds": float(samples.size / 16000),
        "persisted": False,
    }
    del samples
if args.wav:
    with wave.open(str(args.wav), "rb") as source:
        if (
            source.getframerate() != 16000
            or source.getsampwidth() != 2
            or source.getnchannels() != 1
        ):
            raise ValueError("Expected a 16 kHz mono 16-bit PCM test file")
        audio = (
            np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16).astype(np.float32)
            / 32768
        )
    start = time.perf_counter()
    report["transcription"] = voice.transcribe(audio)
    report["transcription_seconds"] = round(time.perf_counter() - start, 3)
app = QApplication.instance() or QApplication([])
speech = SpeechOutput()
report["speech"] = {
    "available": speech.available,
    "engine": speech.engine,
    "voices": speech.voices(),
    "error": speech.error,
}
if args.speak:
    speech.speak("JARVIS voice system is ready.")
    loop = QEventLoop()
    QTimer.singleShot(4000, loop.quit)
    loop.exec()
    report["speech"]["error_after_playback"] = speech.error
    speech.stop()
print(json.dumps(report, indent=2))
