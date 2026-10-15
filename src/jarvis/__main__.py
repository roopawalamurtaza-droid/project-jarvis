"""Command-line entry point and native desktop launcher."""

from __future__ import annotations

import argparse
import json
import logging
import secrets
import sys
from datetime import datetime, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path

from jarvis.config import load_settings, save_settings
from jarvis.secrets import SecretStore
from jarvis.storage import Store
from jarvis.tasks import TaskEngine


def build_service(settings):
    from jarvis.service import JarvisService

    store = Store(settings.data_dir)
    store.prune(settings.history_retention_days)
    engine = TaskEngine(settings, store)
    return JarvisService(settings, store, engine, SecretStore(settings.data_dir))


def doctor(settings):
    """Inspect capabilities without recording, speaking, downloading or calling a model."""
    import importlib.util
    import platform

    report = {
        "python": platform.python_version(),
        "platform": platform.system(),
        "provider": settings.provider,
        "model": settings.model or "not configured",
        "cloud_allowed": settings.cloud_allowed,
        "save_history": settings.save_history,
        "allowed_roots": [str(path) for path in settings.allowed_roots],
        "packages": {
            name: importlib.util.find_spec(name) is not None
            for name in ["PySide6", "fastapi", "sounddevice", "faster_whisper"]
        },
    }
    from jarvis.health import build_identity, startup_health

    report["build"] = build_identity()
    report["health"] = startup_health(settings)
    try:
        from jarvis.voice import VoiceInput

        report["microphones"] = VoiceInput(settings).devices()
    except Exception:
        report["microphones"] = "Unavailable; select/enable an input device in Windows"
    print(json.dumps(report, indent=2))


def configure_logging(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        data_dir / "jarvis.log", maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger = logging.getLogger("jarvis")
    logger.setLevel(logging.INFO)
    logger.addHandler(handler)
    logger.info("JARVIS started")
    # Third-party HTTP debug logging could expose URLs or credential headers.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def main(argv=None):
    parser = argparse.ArgumentParser(description="JARVIS local-first desktop assistant")
    parser.add_argument("--data-dir", type=Path, help="Settings/database directory")
    parser.add_argument("--model", help="Set the model name for the selected provider")
    parser.add_argument(
        "--doctor", action="store_true", help="Inspect devices and dependencies without recording"
    )
    parser.add_argument(
        "--download-speech-model",
        action="store_true",
        help="Explicitly download the configured offline speech model",
    )
    parser.add_argument("--chat", help="Send one real model message and print the actual result")
    parser.add_argument(
        "--verify-computer-use",
        action="store_true",
        help="Phase 5 isolated executor check; --verification-actions permits real Notepad typing/saving",
    )
    parser.add_argument(
        "--verification-browser",
        action="store_true",
        help="Also exercise an isolated visible Chrome session and Google search; CAPTCHA requires human interaction",
    )
    parser.add_argument(
        "--verify-reference-ui",
        action="store_true",
        help="Capture the actual Windows reference UI with isolated data and no microphone",
    )
    parser.add_argument(
        "--verification-live",
        action="store_true",
        help="Also verify the configured local model's real UI streaming",
    )
    parser.add_argument(
        "--verify-phase4",
        action="store_true",
        help="Verify isolated Windows action diagnostics; --verification-actions permits real app/browser launches; no microphone",
    )
    parser.add_argument(
        "--verify-phase3",
        action="store_true",
        help="Exercise the native command center with isolated generated data; no microphone",
    )
    parser.add_argument(
        "--verify-voice-update",
        action="store_true",
        help="Explicit synthetic voice desktop verification, local AI and speech playback; no microphone",
    )
    parser.add_argument(
        "--verification-actions",
        action="store_true",
        help="Also verify authorized Chrome and VS Code launch during the voice diagnostic",
    )
    parser.add_argument(
        "--smoke-test",
        action="store_true",
        help="Verify desktop/audio modules without recording or model calls",
    )
    parser.add_argument(
        "--serve", action="store_true", help="Run the authenticated local API on 127.0.0.1"
    )
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args(argv)
    try:
        settings = load_settings(args.data_dir)
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        if args.model is not None:
            settings.model = args.model
            save_settings(settings)
        if args.doctor:
            doctor(settings)
            return 0
        if args.download_speech_model:
            from jarvis.voice import download_speech_model

            print(f"Offline speech model ready: {download_speech_model(settings)}")
            return 0
        configure_logging(settings.data_dir)
        if args.verify_computer_use:
            import runpy

            diagnostic_dir = (
                Path(__file__).parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parents[2] / "scripts"
            )
            previous_args = sys.argv
            sys.argv = ["verify_phase5", "--data-dir", str(settings.data_dir)]
            if args.verification_actions:
                sys.argv.append("--actions")
            if args.verification_browser:
                sys.argv.append("--browser")
            try:
                runpy.run_path(str(diagnostic_dir / "verify_phase5.py"), run_name="__main__")
            finally:
                sys.argv = previous_args
            return 0
        if args.verify_reference_ui:
            import runpy

            diagnostic_dir = (
                Path(__file__).parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parents[2] / "scripts"
            )
            previous_args = sys.argv
            sys.argv = [
                "verify_phase45",
                "--native",
                "--data-dir",
                str(settings.data_dir / "ui-verification"),
                "--settings-from",
                str(settings.data_dir),
                "--output",
                str(settings.data_dir / "phase45-ui.png"),
            ]
            if args.verification_live:
                sys.argv.append("--live")
            try:
                runpy.run_path(str(diagnostic_dir / "verify_phase45.py"), run_name="__main__")
            finally:
                sys.argv = previous_args
            return 0
        if args.verify_phase4:
            import runpy

            diagnostic_dir = (
                Path(__file__).parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parents[2] / "scripts"
            )
            previous_args = sys.argv
            sys.argv = ["verify_phase4", "--data-dir", str(settings.data_dir)]
            if args.verification_actions:
                sys.argv.append("--actions")
            try:
                runpy.run_path(str(diagnostic_dir / "verify_phase4.py"), run_name="__main__")
            finally:
                sys.argv = previous_args
            return 0
        if args.verify_phase3:
            import runpy

            diagnostic_dir = (
                Path(__file__).parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parents[2] / "scripts"
            )
            previous_args = sys.argv
            sys.argv = ["verify_phase3", "--data-dir", str(settings.data_dir)]
            try:
                runpy.run_path(str(diagnostic_dir / "verify_phase3.py"), run_name="__main__")
            finally:
                sys.argv = previous_args
            return 0
        if args.verify_voice_update:
            import runpy

            diagnostic_dir = (
                Path(__file__).parent
                if getattr(sys, "frozen", False)
                else Path(__file__).resolve().parents[2] / "scripts"
            )
            previous_args = sys.argv
            sys.argv = ["verify_voice_desktop", "--data-dir", str(settings.data_dir)]
            if args.verification_actions:
                sys.argv.append("--actions")
            sys.path.insert(0, str(diagnostic_dir))
            try:
                runpy.run_path(str(diagnostic_dir / "verify_voice_desktop.py"), run_name="__main__")
            finally:
                sys.argv = previous_args
                sys.path.remove(str(diagnostic_dir))
            return 0
        service = build_service(settings)
        try:
            if args.smoke_test:
                from jarvis.diagnostics import smoke_test

                return smoke_test(service, settings)
            if args.chat:
                print(json.dumps(service.chat(args.chat), indent=2, ensure_ascii=False))
                return 0
            if args.serve:
                if not 1024 <= args.port <= 65535:
                    raise ValueError("Choose an unprivileged port between 1024 and 65535")
                import uvicorn

                from jarvis.api import create_app

                token = service.secret_store.get("api_token")
                if not token:
                    token = secrets.token_urlsafe(32)
                    service.secret_store.set("api_token", token)
                # Token never appears on stdout, in URLs, or in logs.
                print(f"Authenticated JARVIS API: http://127.0.0.1:{args.port}")
                uvicorn.run(
                    create_app(service, token), host="127.0.0.1", port=args.port, access_log=False
                )
                return 0
            from jarvis.desktop import run_desktop

            return run_desktop(service, settings, service.store, service.engine) or 0
        finally:
            service.emergency_stop()
            service.close_computer_use()
            service.store.close()
            logging.getLogger("jarvis").info("JARVIS stopped")
    except Exception as exc:
        # Provider errors are redacted by adapters. Startup failures may include local
        # filesystem paths, so logs persist only the exception class.
        logging.getLogger("jarvis").error("Startup/request failed (%s)", type(exc).__name__)
        if "settings" in locals():
            (settings.data_dir / "startup-error.json").write_text(
                json.dumps(
                    {
                        "error": type(exc).__name__,
                        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                    }
                ),
                encoding="utf-8",
            )
        if args.smoke_test and "settings" in locals():
            (settings.data_dir / "package-verification.json").write_text(
                json.dumps({"error": type(exc).__name__, "detail": str(exc)}), encoding="utf-8"
            )
        print(f"JARVIS could not complete the request: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
