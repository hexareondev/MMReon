"""Создаёт ярлык MMReon с иконкой.

    python tools/make_shortcut.py             — на рабочем столе
    python tools/make_shortcut.py --startup   — ещё и в автозагрузке (то же, что галочка в настройках)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mmreon import shortcuts  # noqa: E402


def main():
    if os.name != "nt":
        sys.exit("Ярлыки создаются только в Windows.")
    for kind in ["Desktop"] + (["Startup"] if "--startup" in sys.argv else []):
        lnk = shortcuts.create(kind)
        print(f"Ярлык создан: {lnk}" if lnk else f"Не удалось создать ярлык ({kind})")


if __name__ == "__main__":
    main()
