# Recognition completion repair — 13 October 2026

The user reported a persistent Recognizing speech message with Voice still in
Wake Word Listening and no new words in chat. The app had been closed by inspection;
no running process was treated as live diagnostic evidence.

The exact state was reproduced in real Qt event handling with fake capture:
transcribing followed by ignored or empty left the primary status unchanged.
Wake misses normally discard unrelated audio and produce no chat message. This
completed recognition was therefore presented as an ongoing operation. Empty
follow-ups and paused/muted recognition also needed explicit completion status.

Version 0.2.1 handles all those terminal paths, updates the voice state display,
and retains the bounded listening/timeout and microphone permission boundaries.
An unmatched headset interruption transcript now emits ignored completion too.
Real pending transcription is still shown as recognizing; time alone never
pretends it completed. Late results cannot undo pause/mute or reopen capture.
Logs contain event outcomes and elapsed time, not recognized text or audio.

The initial three regression cases failed before the repair. Twelve new cases
cover ignored/empty recovery, the next valid wake command, honest pending work,
playback completion, six cancelled-result cases, and the actual input worker's
unmatched stop phrase. The initial full run exposed the missing pause/mute status
reset; that was fixed before final testing. The packaged diagnostic now injects
an unrelated utterance, verifies completion in wake mode with no chat request,
then exercises a valid wake, local AI, speech, follow-up and sleep.

Final tests: **295 passed in 47.93s**, Ruff lint and 46 format checks passed.
Frozen GUI smoke and the extended voice diagnostic both exited 0 against runtime
commit `d1f0fe0622a4`, version 0.2.1. Unmatched generated speech returned to wake
listening without a chat request; the next valid wake/local AI/playback turn
succeeded. The replacement was launched with preserved settings. Build hashes,
packaging and transfer results are recorded in NEXT_STEPS.md.
The user subsequently confirmed the actual microphone wake/time request answers
and returns to listening on 0.2.1. This is user-reported live acceptance, separate
from generated-speech measurements and the untested broader acoustic conditions.

This repair addresses reproduced completed-result handling. It
does not claim native Whisper inference can be forcibly interrupted or that
human wake accuracy under noise/accents is guaranteed. If actual inference hangs,
use Pause/Resume and retain the privacy-safe lifecycle logs for investigation.
