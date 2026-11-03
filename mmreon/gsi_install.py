"""Конфиг Game State Integration в папке Доты: поиск, установка, обновление."""
from __future__ import annotations

import os
import re
from pathlib import Path

CFG_NAME = "gamestate_integration_mmreon.cfg"
DOTA_SUBPATH = Path("steamapps/common/dota 2 beta/game/dota/cfg")

TEMPLATE = """"MMReon"
{{
    "uri"           "http://127.0.0.1:{port}/"
    "timeout"       "5.0"
    "buffer"        "0.0"
    "throttle"      "1.0"
    "heartbeat"     "30.0"
    "data"
    {{
        "provider"  "1"
        "map"       "1"
        "player"    "1"
        "hero"      "1"
        "items"     "1"
    }}
    "auth"
    {{
        "token"     "{token}"
    }}
}}
"""


def steam_libraries() -> list[Path]:
    roots = []
    if os.name == "nt":
        import winreg
        for hive, key, value in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam", "SteamPath"),
                                 (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam", "InstallPath")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    roots.append(Path(winreg.QueryValueEx(k, value)[0]))
            except OSError:
                pass
    libs = []
    for root in roots:
        libs.append(root)
        vdf = root / "steamapps" / "libraryfolders.vdf"
        if vdf.exists():
            for p in re.findall(r'"path"\s+"([^"]+)"', vdf.read_text(encoding="utf-8", errors="ignore")):
                libs.append(Path(p.replace("\\\\", "\\")))
    seen, result = set(), []
    for lib in libs:
        k = str(lib).lower()
        if k not in seen:
            seen.add(k)
            result.append(lib)
    return result


def find_cfg_dir(library: Path | None = None) -> Path | None:
    libs = [library] if library else steam_libraries()
    return next((lib / DOTA_SUBPATH for lib in libs if (lib / DOTA_SUBPATH).exists()), None)


def render(cfg: dict) -> str:
    return TEMPLATE.format(port=cfg["gsi_port"], token=cfg["gsi_token"])


def install(cfg: dict, library: Path | None = None) -> Path | None:
    target = find_cfg_dir(library)
    if not target:
        return None
    out_dir = target / "gamestate_integration"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / CFG_NAME
    out.write_text(render(cfg), encoding="utf-8")
    return out


def resolve_cfg_dir(folder: Path) -> Path | None:
    """Папка cfg Доты по любой папке, которую выбрал пользователь:
    библиотека Steam, steamapps, папка «dota 2 beta» или сама cfg."""
    folder = Path(folder)
    candidates = [folder / DOTA_SUBPATH, folder / Path(*DOTA_SUBPATH.parts[1:]),
                  folder / "game" / "dota" / "cfg", folder / "dota" / "cfg", folder]
    for c in candidates:
        if c.name == "cfg" and c.parent.name == "dota" and c.exists():
            return c
    return None


def install_into(cfg: dict, folder: Path) -> Path | None:
    target = resolve_cfg_dir(folder)
    if not target:
        return None
    out_dir = target / "gamestate_integration"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / CFG_NAME
    out.write_text(render(cfg), encoding="utf-8")
    return out


def status(cfg: dict) -> dict:
    """Найдена ли Дота и установлен ли актуальный конфиг MMReon."""
    try:
        target = find_cfg_dir()
    except OSError:
        target = None
    custom = cfg.get("dota_cfg_dir")
    if not target and custom and Path(custom).exists():
        target = Path(custom)
    if not target:
        return {"dota_found": False, "installed": False}
    path = target / "gamestate_integration" / CFG_NAME
    installed = path.exists() and path.read_text(encoding="utf-8", errors="ignore") == render(cfg)
    return {"dota_found": True, "installed": installed, "path": str(path)}


def auto_install(cfg: dict) -> str | None:
    """При запуске: если Дота найдена, а конфига MMReon нет — кладём его сами."""
    try:
        target = find_cfg_dir()
        if not target:
            return None
        path = target / "gamestate_integration" / CFG_NAME
        if path.exists():
            return None
        install(cfg)
        return f"[GSI] конфиг установлен: {path}"
    except OSError:
        return None


def ensure_current(cfg: dict) -> str | None:
    """Если конфиг уже установлен, но устарел (нет новых разделов) — переписывает его.

    Возвращает сообщение для журнала или None, если ничего не менялось.
    """
    try:
        target = find_cfg_dir()
        if not target:
            return None
        path = target / "gamestate_integration" / CFG_NAME
        if not path.exists():
            return None
        if path.read_text(encoding="utf-8", errors="ignore") == render(cfg):
            return None
        path.write_text(render(cfg), encoding="utf-8")
        return "[GSI] конфиг в папке Доты обновлён — перезапустите Доту, чтобы она его подхватила"
    except OSError:
        return None
