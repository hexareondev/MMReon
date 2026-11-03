"""Ярлыки Windows: рабочий стол и автозагрузка. Работает и для скрипта, и для собранного .exe."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from .config import ASSETS_DIR, ROOT

NAME = "MMReon.lnk"
CREATE_NO_WINDOW = 0x08000000

_PS_CREATE = r"""
$shell = New-Object -ComObject WScript.Shell
$s = $shell.CreateShortcut($env:MMR_LNK)
$s.TargetPath = $env:MMR_TARGET
$s.Arguments = $env:MMR_ARGS
$s.WorkingDirectory = $env:MMR_ROOT
$s.IconLocation = $env:MMR_ICON
$s.Description = 'MMReon — трекер рейтинга Dota 2'
$s.Save()
"""


def launch_command() -> tuple[str, str]:
    """(программа, аргументы) для запуска MMReon без консоли."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else Path(sys.executable)
    return str(exe), f'"{ROOT / "MMReon.pyw"}"'


def folder(kind: str) -> Path | None:
    """kind: Desktop или Startup."""
    if os.name != "nt":
        return None
    out = subprocess.run(["powershell", "-NoProfile", "-Command", f"[Environment]::GetFolderPath('{kind}')"],
                         capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    path = out.stdout.strip()
    return Path(path) if path else None


def create(kind: str) -> Path | None:
    target_dir = folder(kind)
    if not target_dir:
        return None
    lnk = target_dir / NAME
    exe, args = launch_command()
    if kind == "Startup":
        args = (args + " --tray").strip()     # при входе в Windows — сразу в трей, без окна
    env = dict(os.environ, MMR_LNK=str(lnk), MMR_TARGET=exe, MMR_ARGS=args, MMR_ROOT=str(ROOT),
               MMR_ICON=str(ASSETS_DIR / "mmreon.ico"))
    res = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", _PS_CREATE],
                         env=env, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW)
    return lnk if res.returncode == 0 and lnk.exists() else None


def autostart_enabled() -> bool:
    d = folder("Startup")
    return bool(d and (d / NAME).exists())


def set_autostart(enabled: bool) -> bool:
    d = folder("Startup")
    if not d:
        return False
    lnk = d / NAME
    if enabled:
        return create("Startup") is not None
    try:
        lnk.unlink(missing_ok=True)
        return True
    except OSError:
        return False
