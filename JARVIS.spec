# -*- mode: python ; coding: utf-8 -*-
from PyInstaller.utils.hooks import collect_all

datas = [('build/build_info.json', 'jarvis'), ('src/jarvis/assets', 'jarvis/assets'), ('scripts/verify_phase5.py', 'jarvis'), ('scripts/verify_phase45.py', 'jarvis'), ('scripts/verify_voice_desktop.py', 'jarvis'), ('scripts/verify_handsfree.py', 'jarvis'), ('scripts/verify_phase3.py', 'jarvis'), ('scripts/verify_phase4.py', 'jarvis')]
binaries = []
hiddenimports = ['verify_phase5', 'verify_phase45', 'verify_phase4', 'verify_phase3', 'verify_voice_desktop', 'verify_handsfree', 'jarvis.desktop', 'jarvis.voice', 'PySide6.QtTextToSpeech', 'PySide6.QtMultimedia', 'faster_whisper', 'sounddevice', 'webrtcvad', '_webrtcvad']
tmp_ret = collect_all('tzdata')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('faster_whisper')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('ctranslate2')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]
tmp_ret = collect_all('_sounddevice_data')
datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]

for automation_package in ('playwright', 'pywinauto', 'comtypes'):
    tmp_ret = collect_all(automation_package)
    datas += tmp_ret[0]; binaries += tmp_ret[1]; hiddenimports += tmp_ret[2]


a = Analysis(
    ['scripts/desktop_entry.py'],
    pathex=['src', 'scripts'],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=['scripts/pyinstaller-hooks'],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PySide6.QtWebEngineCore', 'PySide6.QtWebEngineWidgets', 'PySide6.QtWebEngineQuick'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='JARVIS',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='JARVIS',
)
