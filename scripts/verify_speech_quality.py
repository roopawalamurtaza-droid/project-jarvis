"""Compare native Windows synthesis using synthetic text, never microphone audio.

The installed PySide6 binding does not expose QTextToSpeech.synthesize. WinRT
therefore runs through the same Windows.Media.SpeechSynthesis backend directly;
SAPI uses System.Speech. The resulting synthetic WAV fixtures are transcribed
with the existing offline Whisper model. This is diagnostic evidence, not a
substitute for human listening or real microphone accuracy measurements.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
import wave
from pathlib import Path

import numpy as np

from jarvis.config import load_settings
from jarvis.voice import VoiceInput

CASES = {
    "sentence": "Ready. Your task is complete.",
    "numbered_list": "1. Open Chrome.\n2. Check the downloads folder.",
    "markdown": "**Ready.**\n- Your task is complete.\n- Ask me for help.",
    "isolated_dot": "Status: ready.\n.\nAwaiting your command.",
    "spaced_dots": "Ready . Your task is complete .",
    "letter_dots": "J.A.R.V.I.S. is ready. The file is README.md.",
    "url": "See https://example.com/docs. It was updated on 2026-10-13.",
}


POWERSHELL = r"""
param([string]$CasesPath, [string]$OutputDirectory)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Runtime.WindowsRuntime
Add-Type -AssemblyName System.Speech
[Windows.Media.SpeechSynthesis.SpeechSynthesizer, Windows.Media.SpeechSynthesis, ContentType=WindowsRuntime] | Out-Null
$cases = Get-Content -LiteralPath $CasesPath -Raw | ConvertFrom-Json
$synth = New-Object Windows.Media.SpeechSynthesis.SpeechSynthesizer
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.IsGenericMethod -and
    $_.GetGenericArguments().Count -eq 1 -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
} | Select-Object -First 1
$await = $asTask.MakeGenericMethod([Windows.Media.SpeechSynthesis.SpeechSynthesisStream])
$sapi = New-Object System.Speech.Synthesis.SpeechSynthesizer
$records = @()
foreach ($entry in $cases.PSObject.Properties) {
    $operation = $synth.SynthesizeTextToStreamAsync([string]$entry.Value)
    $task = $await.Invoke($null, @($operation))
    $task.Wait()
    $stream = $task.Result
    $path = Join-Path $OutputDirectory ('winrt-' + $entry.Name + '.wav')
    $file = [System.IO.File]::Create($path)
    try { [System.IO.WindowsRuntimeStreamExtensions]::AsStreamForRead($stream).CopyTo($file) }
    finally { $file.Dispose(); $stream.Dispose() }
    $records += @{ engine='winrt'; voice=$synth.Voice.DisplayName; case=$entry.Name; path=$path }
    $path = Join-Path $OutputDirectory ('sapi-' + $entry.Name + '.wav')
    $format = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo(16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, [System.Speech.AudioFormat.AudioChannel]::Mono)
    $sapi.SetOutputToWaveFile($path, $format)
    $sapi.Speak([string]$entry.Value)
    $sapi.SetOutputToNull()
    $records += @{ engine='sapi'; voice=$sapi.Voice.Name; case=$entry.Name; path=$path }
}
$synth.Dispose()
$sapi.Dispose()
$records | ConvertTo-Json -Depth 4
"""


def read_audio(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as source:
        if source.getsampwidth() != 2:
            raise ValueError("Expected 16-bit synthetic PCM")
        channels, rate = source.getnchannels(), source.getframerate()
        audio = np.frombuffer(source.readframes(source.getnframes()), dtype=np.int16)
        samples = audio.astype(np.float32).reshape(-1, channels).mean(axis=1) / 32768
    if rate != 16_000:
        samples = np.interp(
            np.arange(int(len(samples) * 16_000 / rate)) * rate / 16_000,
            np.arange(len(samples)),
            samples,
        ).astype(np.float32)
    return samples


def verify_playback(output: Path, select_first_speaker: bool) -> dict:
    """Exercise real Qt playback completion and stop without recording a mic."""
    from PySide6.QtCore import QEventLoop, QTimer
    from PySide6.QtWidgets import QApplication

    from jarvis.voice import SpeechOutput

    app = QApplication.instance() or QApplication([])
    devices = SpeechOutput.output_devices()
    selected = devices[0]["id"] if devices and select_first_speaker else None
    speech = SpeechOutput(output_device=selected)
    report = {
        "engine": speech.engine,
        "selected_device": selected,
        "output_devices": devices,
        "available": speech.available,
        "error": speech.error,
        "finished": [],
        "states": [],
        "timed_out": False,
    }
    if not speech.available:
        raise RuntimeError(speech.error)
    loop = QEventLoop()
    start = time.perf_counter()

    def finished():
        report["finished"].append(round(time.perf_counter() - start, 3))
        if len(report["finished"]) == 2:
            loop.quit()

    speech.on_finished(finished)
    speech._tts.stateChanged.connect(
        lambda state: report["states"].append(
            {"state": state.name, "seconds": round(time.perf_counter() - start, 3)}
        )
    )
    speech.set_rate(0.0)
    speech.speak("This extended sentence verifies interruption. " * 8)
    QTimer.singleShot(700, speech.stop)
    QTimer.singleShot(950, lambda: speech.speak("**Ready.**"))

    def timeout():
        report["timed_out"] = True
        loop.quit()

    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(timeout)
    timer.start(10_000)
    loop.exec()
    timer.stop()
    report["speaking_at_end"] = speech.speaking
    report["error_after_playback"] = speech.error
    speech.stop()
    output.joinpath("playback-report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    if report["timed_out"] or report["speaking_at_end"] or len(report["finished"]) != 2:
        raise RuntimeError("Qt completion/stop lifecycle verification failed")
    # Hold the QApplication reference through the final native speech teardown.
    _ = app
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--synthesize", action="store_true", help="Generate synthetic WAV fixtures")
    parser.add_argument(
        "--normalized", action="store_true", help="Normalize speech before synthesis"
    )
    parser.add_argument("--playback", action="store_true", help="Opt in to real speaker output")
    parser.add_argument(
        "--select-first-speaker",
        action="store_true",
        help="Verify explicit Qt output-device selection",
    )
    args = parser.parse_args()
    output = args.data_dir.resolve() / "speech-quality"
    output.mkdir(parents=True, exist_ok=True)
    fixtures = output / ("normalized" if args.normalized else "raw")
    fixtures.mkdir(parents=True, exist_ok=True)
    cases = dict(CASES)
    if args.normalized:
        from jarvis.speech_text import normalize_speech

        cases = {name: normalize_speech(value) for name, value in cases.items()}
    cases_path = fixtures / "cases.json"
    cases_path.write_text(json.dumps(cases, ensure_ascii=False), encoding="utf-8")
    manifest = output / ("normalized-manifest.json" if args.normalized else "raw-manifest.json")
    if args.synthesize:
        script = fixtures / "synthesize.ps1"
        script.write_text(POWERSHELL, encoding="utf-8")
        executable = (
            Path(os.environ["SystemRoot"]) / "System32/WindowsPowerShell/v1.0/powershell.exe"
        )
        completed = subprocess.run(
            [
                str(executable),
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                str(script),
                str(cases_path),
                str(fixtures),
            ],
            check=True,
            capture_output=True,
            text=True,
            timeout=60,
        )
        records = json.loads(completed.stdout)
        manifest.write_text(json.dumps(records, indent=2), encoding="utf-8")
    else:
        records = json.loads(manifest.read_text(encoding="utf-8"))
    voice = VoiceInput(load_settings(args.data_dir))
    for record in records:
        samples = read_audio(Path(record["path"]))
        start = time.perf_counter()
        record["transcript"] = voice.transcribe(samples)
        record["duration_seconds"] = round(samples.size / 16_000, 3)
        record["transcription_seconds"] = round(time.perf_counter() - start, 3)
        record["input_text"] = cases[record["case"]]
        print(json.dumps(record))
    report = output / ("normalized-report.json" if args.normalized else "raw-report.json")
    report.write_text(json.dumps(records, indent=2), encoding="utf-8")
    if args.playback:
        print(json.dumps({"playback": verify_playback(output, args.select_first_speaker)}))


if __name__ == "__main__":
    main()
