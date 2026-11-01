"""Кладёт конфиг GSI для MMReon в папку Доты.

    python tools/install_gsi.py                      — найти Доту автоматически
    python tools/install_gsi.py "D:\\SteamLibrary"   — указать библиотеку Steam вручную
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mmreon import config, gsi_install  # noqa: E402


def main():
    cfg = config.load()
    library = Path(sys.argv[1]) if len(sys.argv) > 1 else None
    out = gsi_install.install(cfg, library)
    if not out:
        sys.exit("Папка Доты не найдена. Укажите библиотеку Steam: python tools/install_gsi.py \"D:\\SteamLibrary\"")
    print(f"Готово: {out}")
    print("Добавьте в параметры запуска Доты в Steam: -gamestateintegration")
    print("и перезапустите игру, если она открыта.")


if __name__ == "__main__":
    main()
