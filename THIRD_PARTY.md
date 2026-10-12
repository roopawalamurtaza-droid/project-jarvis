# Third-party components

Source/dependency licenses must be preserved when distributing a packaged build.
The development application does not change their licensing or model terms.

- PySide6/Qt: LGPLv3/GPLv3/commercial terms as applicable; packaged DLLs remain
  separate in the one-directory build. See https://doc.qt.io/qtforpython-6/licenses.html.
- faster-whisper/CTranslate2: MIT; see upstream repository license files.
- webrtcvad-wheels: Windows binary packaging of the WebRTC Python VAD interface;
  preserve Python and WebRTC third-party license notices.
- tzdata: IANA timezone data for Windows ZoneInfo support.
- openWakeWord/Porcupine were researched, not bundled. Included openWakeWord
  models have separate noncommercial terms; they are not part of this build.
- Whisper model: review the upstream OpenAI Whisper/Systran model license and card.
- Ollama and each chat model have separate licenses; Ollama is external to the package.
- Other Python package license metadata is installed in `.venv` and locked by `uv.lock`.

The package script includes the dependencies' collected package data; review
THIRD_PARTY and the packaged license notices before redistributing. This is an
internal development build, not a signed public release.
