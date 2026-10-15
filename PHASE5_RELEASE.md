# Phase 5 — first computer-use gates (0.5.0)

Continue `codex/phase5-computer-use` in the existing public repository:
https://github.com/roopawalamurtaza-droid/project-jarvis/tree/codex/phase5-computer-use.
The earlier request to make the repository public remains in effect. The verified
0.4.5 branch/build is preserved. This increment implements the first acceptance
gates; the entire OMNI-AUTONOMY directive is not complete.

## Architecture and execution

Existing voice/text → JarvisService → human-only computer_commands parser or
reviewed typed AI proposal → ActionDispatcher → central TaskEngine permissions
and one-use approval → native adapter → observed verification → receipt/response.
Plans are bounded to six serial tools with dependencies, cancellation, restart
cancellation and partial-failure history. Model prose, webpages and memories do
not enter the human command parser or authorize actions. No separate large model
is spawned per adapter. Ordinary chat still has no execution authority.

- `computer_windows.py`: one COM/UIA owner; English modern Windows Notepad.
  Creates a separate empty window, preserving restored user tabs; enters literal
  text through ValuePattern, invokes observed File → Save and exact Save As
  controls, then compares actual UTF-8 file contents/hash. No direct file-write
  substitute, arbitrary keys/mouse, clipboard or guessed clicks.
- `computer_browser.py`: one Playwright owner; visible installed Chrome/Edge in
  an isolated nonpersistent context. No personal profile/cookie/password reuse
  or silent browser fallback. Actual DOM results, URL/title, tabs and measured
  scroll/history observations establish completion.
- Shared PySide6 futuristic UI/core, Mini, SQLite memory, Whisper/WebRTC VAD,
  Windows speech, grants and optional local authenticated API remain intact.
  Computer Use is appended at index 11 via Ctrl+K/Mission Control; old indices
  and the seven reference sidebar destinations remain.

## Registered tools

| Tool | Actual supported behavior |
| --- | --- |
| desktop_write_note | New `.txt`, ≤4,000 characters, existing permitted parent; exact path/text preview/approval; native Notepad save and byte verification |
| browser_search_open | Google search; uniquely observed result matching an explicit official host; click and final-page verification; challenge/ambiguity stops |
| browser_navigate / browser_new_tab | Public HTTPS in the owned browser, actual final-page observation |
| browser_read | Bounded untrusted page body; protected fields excluded; raw body not persisted |
| browser_scroll / browser_back / browser_forward | Actual page position/history and resulting observation |
| browser_tabs / browser_switch_tab / browser_close_tab | Owned observed tab IDs; close is approved against a frozen tab ID |
| browser_user_interaction | Explicit temporary human challenge grant below; revocation needs no approval |

New `computer_use_enabled` and `browser_automation_enabled` default **false**;
existing desktop/browser grants and allowed folders still apply. Desktop paths
come from Windows' actual configured Desktop, including redirection; they must
still be allowed. Never invent a project path or automatically add a root.
Existing files are not overwritten. Elevated windows, locked/security desktops,
protected fields and unidentified/ambiguous controls are refused.

Adapter calls have bounded deadlines, queues, observations and no automatic
network retries. Stop/cancel reaches active adapters at safe boundaries; native
UIA/Playwright calls cannot be force-killed safely. A Save already accepted by
Windows cannot be reversed by cancellation. Pause cancels current input and
blocks new actions; resume permits new explicit requests rather than replay.
Restart cancels interrupted plans/approvals. Existing user documents are not
closed or discarded to make a test pass.

## Human browser interaction and privacy

Normal browser requests allow public HTTPS GET/HEAD only. Private/reserved DNS
destinations, unsafe redirects, service workers and WebSockets are blocked.
These checks are an application guard, not an OS network sandbox; a DNS
rebinding race and browser subprocess behavior remain limits.

An observed login/CAPTCHA stops automation. **Request human browser interaction**
creates a one-use approval with an explicit modal: the owned browser may send
public HTTPS POST requests for five minutes, **including page scripts**. This
cannot distinguish human gestures cryptographically. The human handles the
visible challenge; no automated form submission is performed. End human
interaction, Stop, expiry or the next automatic request revokes the temporary
grant. No authentication/CAPTCHA bypass or personal-profile attachment.

The initial Google test encountered CAPTCHA. Its read-only diagnostic blocked
CAPTCHA POST requests and was intentionally stopped. The user reported Chrome
disappearing; the recorded diagnostic shutdown does not prove a spontaneous
crash. The new human handoff addresses that limitation. Intentional owned-browser
closure/recreation was tested separately, not every possible browser crash.

Note text exists only in live approval memory and is cleared after execution;
restart cannot replay it. Persisted task/plan receipts omit note/page bodies.
Audit records contain state/identifiers, not recordings/screenshots/passwords.
Web content remains untrusted and never becomes a permission grant. `.local`,
settings, protected credentials, personal memory, browser data and models remain
excluded from Git and transfer archives.

## Evidence and unfinished capabilities

Actual local Windows access was verified. Native Notepad saved 92 generic UTF-8
bytes including Unicode/symbols, with content/hash verification and preserved
user tabs. The integrated JarvisService/TaskEngine diagnostic separately approved,
typed and saved `Testing JARVIS automation` and verified its actual file. Outputs
were within `C:\Jarvis\build`, not the user's Desktop.

Actual isolated Chrome verified Python.org and GitHub navigation, scrolling,
tabs/switching/history/close and fresh-context recovery after intentional closure.
The Google search gate is unverified whenever CAPTCHA blocks it. NEXT_STEPS.md
records current source/frozen/human evidence; never infer new voice acceptance
from the earlier 0.4.5 microphone check.

General Windows controls/apps, vision/screenshots, browser uploads/downloads,
consequential forms, research comparisons, file organization/PDF/spreadsheet
reports, repository editing/development commands and durable schedules remain
unimplemented in this increment. Internal guarded browser helpers are not
registered public capabilities. No unrestricted shell/admin, purchase/payment,
message sending, private-data sharing or deployment tools. Do not expand these
milestones before the first desktop/browser gates are verified.

## Install, run, build and test

```powershell
git clone -b codex/phase5-computer-use https://github.com/roopawalamurtaza-droid/project-jarvis.git C:\Jarvis
cd C:\Jarvis
uv sync --frozen --all-extras
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests scripts
.\.venv\Scripts\python.exe -m ruff format --check src tests scripts
.\scripts\package.ps1
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\.local
```

Install supported Chrome/Edge normally. The build bundles Playwright's driver,
pywinauto, comtypes and pywin32; UI Automation is supplied by Windows. No global
browser installation/profile replacement. Existing local speech/Ollama model
setup remains separate; deterministic workflows need no API key. Cloud variable
names remain `OPENAI_API_KEY` and `GEMINI_API_KEY`, with cloud consent.

```powershell
# Actually types/saves a generic note in an isolated permitted test folder:
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\build\phase5-local-check --verify-computer-use --verification-actions
# Additionally opens public Chrome sites and attempts actual Google search:
.\dist\JARVIS\JARVIS.exe --data-dir C:\Jarvis\build\phase5-local-check --verify-computer-use --verification-actions --verification-browser
```

The browser diagnostic marks CAPTCHA as blocked, not passed; it captures no
microphone and calls no cloud model. For human acceptance, enable both computer
permissions in Settings, retain wake/Speak replies and add the actual Desktop to
permitted roots if needed. Speak the note objective, review its exact path/text
in Mission Control and approve. Check the saved file. Request the official Python
search, use the reviewed human mode for any challenge, end it and repeat the
search; check the actual final page/follow-up/pause/Stop. Preserve `.local` and
the old complete build during replacement. Keep the whole new folder together.
Unsigned/fresh-PC, broad acoustics, localized/legacy Notepad and physical
locked/elevated-desktop acceptance remain separate and unverified.
