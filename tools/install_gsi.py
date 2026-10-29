"""Кладёт конфиг GSI для MMReon в папку Доты.

    python tools/install_gsi.py            — найти Доту автоматически
    python tools/install_gsi.py "D:\\SteamLibrary"   — указать библиотеку Steam вручную
"""
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mmreon import config  # noqa: E402

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
    }}
    "auth"
    {{
        "token"     "{token}"
    }}
}}
"""


def steam_libraries():
    roots = []
    if os.name == "nt":
        import winreg
        for hive, key in ((winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
                          (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam")):
            try:
                with winreg.OpenKey(hive, key) as k:
                    name = "SteamPath" if hive == winreg.HKEY_CURRENT_USER else "InstallPath"
                    roots.append(Path(winreg.QueryValueEx(k, name)[0]))
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
        key = str(lib).lower()
        if key not in seen:
            seen.add(key)
            result.append(lib)
    return result


def main():
    cfg = config.load()
    libs = [Path(sys.argv[1])] if len(sys.argv) > 1 else steam_libraries()
    target = next((lib / DOTA_SUBPATH for lib in libs if (lib / DOTA_SUBPATH).exists()), None)
    if not target:
        sys.exit("Папка Доты не найдена. Укажите библиотеку Steam: python tools/install_gsi.py \"D:\\SteamLibrary\"")
    out_dir = target / "gamestate_integration"
    out_dir.mkdir(exist_ok=True)
    out = out_dir / CFG_NAME
    out.write_text(TEMPLATE.format(port=cfg["gsi_port"], token=cfg["gsi_token"]), encoding="utf-8")
    print(f"Готово: {out}")
    print("Добавьте в параметры запуска Доты в Steam: -gamestateintegration")
    print("и перезапустите игру, если она открыта.")


if __name__ == "__main__":
    main()
