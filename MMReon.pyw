"""Запуск MMReon без окна консоли: двойной клик по этому файлу.

Файлы .pyw Windows открывает через pythonw.exe — консоль не появляется.
Всё, что трекер писал бы в консоль, сохраняется в data/mmreon.log.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
(ROOT / "data").mkdir(exist_ok=True)
log = open(ROOT / "data" / "mmreon.log", "a", encoding="utf-8", buffering=1)
sys.stdout = sys.stderr = log

import run  # noqa: E402

run.main()
