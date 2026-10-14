"""Layout-specific glass surfaces; shared graphics tokens live in ui_components."""

STYLE = """
QFrame#MainShell { background:#030e17; border:1px solid #225169; border-radius:15px; }
QFrame#AssistantCanvas { background:qlineargradient(x1:0,y1:0,x2:1,y2:1,
 stop:0 #061923,stop:0.5 #03131d,stop:1 #04131f);
 border:1px solid #153444; border-radius:13px; }
QWidget#TranscriptSurface, QWidget#MessageRow { background:transparent; }
QScrollArea#Conversation { background:transparent; border:0; }
QFrame#AssistantMessage { background:#081b28; border:1px solid #173547; border-radius:14px; }
QFrame#UserMessage { background:#091b26; border:1px solid #193646; border-radius:14px; }
QTextBrowser#MessageBody { background:transparent; border:0; padding:0; font-size:13px; }
QLabel#MessageAuthor { color:#91bad1; font-size:10px; }
QLabel#AssistantAvatar { background:#07314b; color:#5bd5ff; border:1px solid #33bdf5;
 border-radius:20px; font-size:25px; }
QLabel#UserAvatar { background:#0b2333; color:#a8cbe3; border:1px solid #31516a;
 border-radius:20px; font-size:19px; }
QPushButton#MessageAction { background:transparent; color:#7698b0; border:0;
 padding:0 6px; font-size:10px; min-height:16px; }
QPushButton#MessageAction:hover { color:#4fd1ff; }
QLabel#Greeting { font-size:24px; color:#dfedf4; font-weight:400; }
QLabel#GreetingSubtitle { font-size:17px; color:#9baaba; }
QLabel#SectionEyebrow { font-size:10px; letter-spacing:1px; color:#539cb2; }
QLabel#Capability { font-size:12px; color:#b2c6d7; }
QLabel#ReferenceQuote { color:#8095ad; font-size:12px; }
QLabel#SidebarPrivacy { color:#6e93a7; font-size:10px; }
QLabel#FooterStatus, QLabel#VoiceStatus { color:#7692a7; font-size:10px; }
QFrame#ComposerPanel { background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
 stop:0 #071c29,stop:0.5 #051824,stop:1 #08304a);
 border:1px solid #2586ab; border-radius:22px; }
QPlainTextEdit#MessageInput { background:transparent; border:0; padding:3px;
 font-size:12px; selection-background-color:#1c506b; }
QPushButton#IconButton { background:transparent; border:0; padding:3px; }
QPushButton#Microphone, QPushButton#Interrupt { background:transparent;
 border:1px solid #1a455b; padding:3px 7px; font-size:10px; border-radius:13px; }
QPushButton#QuietButton { background:transparent; border:0; padding:2px 5px; font-size:10px; color:#8eb8cf; }
QCheckBox { font-size:11px; }
QWidget#PresenceDetail { background:transparent; }
"""
