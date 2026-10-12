"""Opt-in, current-user Windows startup registration with an exact fixed command."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

VALUE_NAME = "ProjectJarvis"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"


def startup_command(data_dir: Path) -> str:
    if getattr(sys, "frozen", False):
        args = [sys.executable, "--data-dir", str(data_dir)]
    else:
        args = [sys.executable, "-m", "jarvis", "--data-dir", str(data_dir)]
    return subprocess.list2cmdline(args)


def set_start_with_windows(enabled: bool, data_dir: Path) -> None:
    if sys.platform != "win32":
        if enabled:
            raise RuntimeError("Start with Windows is available only on Windows.")
        return
    import winreg

    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            winreg.SetValueEx(key, VALUE_NAME, 0, winreg.REG_SZ, startup_command(data_dir))
        else:
            try:
                winreg.DeleteValue(key, VALUE_NAME)
            except FileNotFoundError:
                pass
