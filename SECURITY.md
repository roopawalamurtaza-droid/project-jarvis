# Security model

The app runs as the current Windows user. DPAPI protects API credentials at rest;
other local data uses an ordinary SQLite database. Local administrator access or
compromise of the current user's process can bypass these protections. This build
is for trusted personal desktop use, not unattended remote or hostile multi-user use.

- Cloud chat is disabled initially. No provider fallback, private-file upload,
  browser automation, arbitrary command execution, payments or messages exist.
- Model output is conversational text. Only explicit human commands/forms enter
  the execution engine; model output and document contents cannot grant permissions.
- File tools have strict schemas and configured roots, protected-file rules,
  link/junction rejection, read limits and execution-time path checks.
- Manual mode approves state changes; sensitive directory creation always asks.
  Approvals are one-use, expire in ten minutes and disappear on restart/stop.
- API authentication is constant-time comparison of a strong bearer token. The
  optional server binds only to loopback, disables access logs and public docs,
  and has no wildcard CORS. Never forward its port to the internet.
- HTTP provider errors omit credentials and raw response bodies. Rotating local
  logs record lifecycle/error classes; structured audit records capture task state,
  approvals and provider/token metadata, rather than prompts/file contents.
- Conversation persistence, speech playback and microphone capture require explicit
  user controls. Audio buffers are bounded and ephemeral. Wake words and passive
  screen capture are absent.
- Emergency stop cancels network work and prevents new actions. Already executing
  OS actions cannot be undone. Native speech recognition results can be discarded,
  but inference itself cannot safely be terminated in the current process.

Use Windows account isolation and disk encryption for sensitive data. Memory
deletion is logical, not a guarantee of forensic erasure. Exported files contain
personal data. Revoking a stored key does not unset a key supplied separately by
environment variable; remove that variable too.

Dependencies are locked and a vulnerability check is part of release verification.
Model files are fetched only by explicit setup from the configured speech-model
repository. This build has no updater and does not claim signed release verification.
Do not install unsigned updates from untrusted sources.

Security regressions are exercised by automated tests. See TESTING.md for actual
test results and limitations. No real customer messages or financial transactions
are authorized during development.

