"""Обновление MMReon одной кнопкой.

Если MMReon запущен из папки, склонированной git, — забираем новые коммиты (git pull)
и доустанавливаем зависимости. Если это собранный .exe — показываем ссылку на новую версию.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys

from .config import ROOT

RELEASES_URL = "https://github.com/hexareondev/mmreon/releases"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def _git(*args, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)


def mode() -> str:
    if getattr(sys, "frozen", False):
        return "manual"
    if (ROOT / ".git").exists() and shutil.which("git"):
        return "git"
    return "manual"


def check() -> dict:
    """{'mode', 'available', 'count', 'changes', 'error', 'url'}"""
    m = mode()
    if m == "manual":
        return {"mode": m, "available": None, "url": RELEASES_URL}
    try:
        fetch = _git("fetch", "--quiet", "origin")
        if fetch.returncode != 0:
            return {"mode": m, "available": None, "error": "Не удалось связаться с GitHub: " + fetch.stderr.strip()[:200]}
        count = _git("rev-list", "--count", "HEAD..@{u}")
        n = int(count.stdout.strip() or 0) if count.returncode == 0 else 0
        log = _git("log", "--format=%s", "HEAD..@{u}") if n else None
        changes = [line for line in (log.stdout.splitlines() if log else []) if line.strip()][:10]
        return {"mode": m, "available": n > 0, "count": n, "changes": changes}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        return {"mode": m, "available": None, "error": f"Ошибка проверки обновлений: {exc}"}


def apply() -> dict:
    """git pull + установка зависимостей. {'ok', 'message'}"""
    if mode() != "git":
        return {"ok": False, "message": "Эту копию MMReon нужно обновить вручную", "url": RELEASES_URL}
    try:
        pull = _git("pull", "--ff-only", timeout=120)
        if pull.returncode != 0:
            return {"ok": False, "message": "git pull не удался: " + (pull.stderr or pull.stdout).strip()[:300]}
        req = ROOT / "requirements.txt"
        if req.exists():
            pip = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                                 capture_output=True, text=True, timeout=600, creationflags=CREATE_NO_WINDOW)
            if pip.returncode != 0:
                return {"ok": False, "message": "Код обновлён, но зависимости не установились: "
                        + pip.stderr.strip()[-300:]}
        return {"ok": True, "message": "Обновлено. MMReon перезапустится."}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"ok": False, "message": f"Ошибка обновления: {exc}"}


def restart_command() -> list[str]:
    """Команда, которой запустить MMReon заново после обновления."""
    from .shortcuts import launch_command
    exe, args = launch_command()
    return [exe] + ([args.strip('"')] if args else [])


def spawn_restart():
    flags = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(restart_command(), cwd=str(ROOT), creationflags=flags, close_fds=True)
