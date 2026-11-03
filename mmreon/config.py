"""Настройки MMReon. Пользовательские значения лежат в data/config.json."""
import json
import os
import secrets
import sys
from pathlib import Path

# В собранном .exe данные лежат рядом с программой, а ресурсы — внутри сборки.
FROZEN = getattr(sys, "frozen", False)
ROOT = Path(sys.executable).resolve().parent if FROZEN else Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
ASSETS_DIR = Path(__file__).resolve().parent / "assets"
CONFIG_PATH = DATA_DIR / "config.json"
MATCHES_PATH = DATA_DIR / "matches.json"
DEBUG_DIR = DATA_DIR / "debug"

DEFAULTS = {
    "gsi_port": 47290,
    "gsi_token": "",                 # создаётся автоматически при первом запуске
    "scan_interval_sec": 2.0,        # как часто смотреть на экран, когда ждём цифру
    "max_delta": 150,                # больше этого за один матч — считаем ошибкой распознавания
    "tesseract_cmd": "",             # путь к tesseract.exe, если он не в PATH
    "widget_enabled": True,          # показывать виджет в главном меню Доты
    "widget_opacity": 1.0,           # непрозрачность виджета, 0.3–1.0
    "widget_anchor": True,           # ставить виджет на панель профиля Доты, клики проходят в игру
    "widget_x": 24,                  # положение виджета на экране (запоминается при перетаскивании)
    "widget_y": 120,
    "notifications": True,           # уведомление Windows, когда записано изменение рейтинга
    "close_to_tray": True,           # крестик прячет окно в трей, выход — из меню значка
    "goal": None,                    # цель по рейтингу: {"rating", "date", "start", "set_at"}
    "dota_cfg_dir": "",              # папка cfg Доты, если её указали вручную
    "setup_done": False,             # первая настройка пройдена — чек-лист больше не показываем
    "setup_dismissed": False,
}

_WINDOWS_TESSERACT = Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
_BUNDLED_TESSERACT = ROOT / "tesseract" / "tesseract.exe"     # кладётся рядом при сборке .exe


def load() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cfg = dict(DEFAULTS)
    if CONFIG_PATH.exists():
        cfg.update(json.loads(CONFIG_PATH.read_text(encoding="utf-8")))
    changed = not CONFIG_PATH.exists()
    if not cfg["gsi_token"]:
        cfg["gsi_token"] = secrets.token_hex(12)
        changed = True
    if _BUNDLED_TESSERACT.exists():
        cfg["tesseract_cmd"] = str(_BUNDLED_TESSERACT)     # своя копия в сборке важнее установленной
    elif not cfg["tesseract_cmd"] and os.name == "nt" and _WINDOWS_TESSERACT.exists():
        cfg["tesseract_cmd"] = str(_WINDOWS_TESSERACT)
        changed = True
    if changed:
        save(cfg)
    return cfg


def save(cfg: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
