"""Обновление MMReon одной кнопкой.

Два режима:
- git — MMReon запущен из папки, склонированной git: git pull, зависимости, перезапуск;
- release — собранный MMReon.exe: берём последний релиз с GitHub, скачиваем архив,
  после выхода программы подменяем файлы (папка data не трогается) и запускаем заново.
"""
from __future__ import annotations

import json
import os
import shutil
import ssl
import subprocess
import sys
import urllib.request
import zipfile

from . import __version__
from .config import DATA_DIR, ROOT

REPO = "hexareondev/mmreon"
RELEASES_URL = f"https://github.com/{REPO}/releases"
API_LATEST = f"https://api.github.com/repos/{REPO}/releases/latest"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
UPDATE_DIR = DATA_DIR / "update"


def _git(*args, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=timeout, creationflags=CREATE_NO_WINDOW)


def _version_tuple(v: str) -> tuple:
    parts = []
    for p in v.lstrip("vV").split("."):
        digits = "".join(ch for ch in p if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts + [0] * (3 - len(parts)))


def mode() -> str:
    if getattr(sys, "frozen", False):
        return "release"
    if (ROOT / ".git").exists() and shutil.which("git"):
        return "git"
    return "manual"


# ---------- git ----------

def _check_git() -> dict:
    fetch = _git("fetch", "--quiet", "origin")
    if fetch.returncode != 0:
        return {"mode": "git", "available": None, "error": "Не удалось связаться с GitHub: " + fetch.stderr.strip()[:200]}
    count = _git("rev-list", "--count", "HEAD..@{u}")
    n = int(count.stdout.strip() or 0) if count.returncode == 0 else 0
    log = _git("log", "--format=%s", "HEAD..@{u}") if n else None
    changes = [line for line in (log.stdout.splitlines() if log else []) if line.strip()][:10]
    return {"mode": "git", "available": n > 0, "count": n, "changes": changes}


def _apply_git() -> dict:
    pull = _git("pull", "--ff-only", timeout=120)
    if pull.returncode != 0:
        return {"ok": False, "message": "git pull не удался: " + (pull.stderr or pull.stdout).strip()[:300]}
    req = ROOT / "requirements.txt"
    if req.exists():
        pip = subprocess.run([sys.executable, "-m", "pip", "install", "-q", "-r", str(req)],
                             capture_output=True, text=True, timeout=600, creationflags=CREATE_NO_WINDOW)
        if pip.returncode != 0:
            return {"ok": False, "message": "Код обновлён, но зависимости не установились: " + pip.stderr.strip()[-300:]}
    return {"ok": True, "message": "Обновлено. MMReon перезапустится.", "restart": "spawn"}


# ---------- релизы GitHub ----------

def _ssl_context() -> ssl.SSLContext:
    """Сертификаты для HTTPS. В собранном .exe Python не всегда находит хранилище Windows,
    поэтому берём набор из certifi (он кладётся в сборку), а если его нет — системный."""
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except Exception:
        return ssl.create_default_context()


def _open(url: str, timeout: int, accept: str | None = None):
    headers = {"User-Agent": "MMReon-updater"}
    if accept:
        headers["Accept"] = accept
    return urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=timeout,
                                  context=_ssl_context())


def _latest_release() -> dict:
    with _open(API_LATEST, 15, "application/vnd.github+json") as resp:
        return json.loads(resp.read().decode("utf-8"))


def _check_release() -> dict:
    rel = _latest_release()
    tag = rel.get("tag_name") or ""
    asset = next((a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".zip")), None)
    newer = _version_tuple(tag) > _version_tuple(__version__)
    notes = [line.strip("-* ").strip() for line in (rel.get("body") or "").splitlines() if line.strip().startswith(("-", "*"))][:10]
    return {"mode": "release", "available": bool(newer and asset), "version": tag.lstrip("vV"),
            "changes": notes, "url": rel.get("html_url") or RELEASES_URL,
            "asset": asset.get("browser_download_url") if asset else None,
            "size_mb": round(asset.get("size", 0) / 1048576, 1) if asset else None}


def _apply_release(info: dict) -> dict:
    url = info.get("asset")
    if not url:
        return {"ok": False, "message": "В релизе нет архива с программой", "url": RELEASES_URL}
    if UPDATE_DIR.exists():
        shutil.rmtree(UPDATE_DIR, ignore_errors=True)
    UPDATE_DIR.mkdir(parents=True)
    archive = UPDATE_DIR / "MMReon.zip"
    with _open(url, 60) as resp, open(archive, "wb") as out:
        shutil.copyfileobj(resp, out, length=1 << 20)
    new_dir = UPDATE_DIR / "new"
    with zipfile.ZipFile(archive) as z:
        for member in z.namelist():                     # защита от путей вида ../
            target = (new_dir / member).resolve()
            if not str(target).startswith(str(new_dir.resolve())):
                return {"ok": False, "message": "Архив обновления повреждён"}
        z.extractall(new_dir)
    # Архив может быть как с файлами в корне, так и с одной папкой внутри.
    src = new_dir
    if not (src / "MMReon.exe").exists():
        inner = [p for p in new_dir.iterdir() if p.is_dir() and (p / "MMReon.exe").exists()]
        if not inner:
            return {"ok": False, "message": "В архиве обновления нет MMReon.exe"}
        src = inner[0]
    # Скрипт подмены файлов: ждёт, пока эта копия закроется, копирует новые файлы
    # поверх старых (папку data не трогает), запускает MMReon и убирает за собой.
    # PowerShell, а не .bat: ему не нужны консольные утилиты, и он работает полностью скрыто.
    def q(path) -> str:
        return "'" + str(path).replace("'", "''") + "'"

    script = DATA_DIR / "mmreon_update.ps1"
    script.write_text(
        "$ErrorActionPreference = 'SilentlyContinue'\r\n"
        f"Wait-Process -Id {os.getpid()} -Timeout 120\r\n"
        f"robocopy {q(src)} {q(ROOT)} /E /XD data /R:3 /W:1 /NFL /NDL /NJH /NJS /NP | Out-Null\r\n"
        f"Start-Process -FilePath {q(ROOT / 'MMReon.exe')} -WorkingDirectory {q(ROOT)}\r\n"
        f"Remove-Item -LiteralPath {q(UPDATE_DIR)} -Recurse -Force\r\n"
        "Remove-Item -LiteralPath $PSCommandPath -Force\r\n",
        encoding="utf-8-sig")      # с BOM — иначе Windows PowerShell 5 исказит русские буквы в путях
    old_bat = DATA_DIR / "mmreon_update.bat"
    if old_bat.exists():
        old_bat.unlink()
    return {"ok": True, "message": f"Версия {info.get('version')} скачана. MMReon перезапустится.",
            "restart": "script", "script": str(script)}


# ---------- общее ----------

_last_check: dict | None = None


def check() -> dict:
    """{'mode', 'available', 'count'/'version', 'changes', 'error', 'url'}"""
    global _last_check
    m = mode()
    try:
        if m == "git":
            info = _check_git()
        elif m == "release":
            info = _check_release()
        else:
            info = {"mode": m, "available": None, "url": RELEASES_URL}
    except (OSError, subprocess.TimeoutExpired, ValueError) as exc:
        info = {"mode": m, "available": None, "error": f"Не удалось проверить обновления: {exc}"}
    _last_check = info
    return info


def apply() -> dict:
    m = mode()
    try:
        if m == "git":
            return _apply_git()
        if m == "release":
            info = _last_check if _last_check and _last_check.get("mode") == "release" else _check_release()
            if not info.get("available"):
                return {"ok": False, "message": "Новой версии нет"}
            return _apply_release(info)
    except (OSError, subprocess.TimeoutExpired, ValueError, zipfile.BadZipFile) as exc:
        return {"ok": False, "message": f"Ошибка обновления: {exc}"}
    return {"ok": False, "message": "Эту копию MMReon нужно обновить вручную", "url": RELEASES_URL}


def restart_command() -> list[str]:
    """Команда, которой запустить MMReon заново после обновления."""
    from .shortcuts import launch_command
    exe, args = launch_command()
    return [exe] + ([args.strip('"')] if args else [])


def spawn_restart(result: dict | None = None):
    """Запуск после выхода: новая копия через git — сразу, обновление .exe — скриптом подмены файлов."""
    if result and result.get("restart") == "script":
        # Только CREATE_NO_WINDOW: вместе с DETACHED_PROCESS Windows его игнорирует,
        # и каждая команда скрипта открывала бы своё консольное окно.
        subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                          "-WindowStyle", "Hidden", "-File", result["script"]],
                         cwd=str(DATA_DIR), creationflags=CREATE_NO_WINDOW | 0x00000200, close_fds=True)
        return
    detached = 0x00000008 | 0x00000200 if os.name == "nt" else 0   # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(restart_command(), cwd=str(ROOT), creationflags=detached, close_fds=True)
