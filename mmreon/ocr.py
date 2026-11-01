"""Распознавание рейтинга и уверенности в ранге с вкладки «Профиль → История».

Вкладку узнаём по золотой подписи «Рейтинг» (assets/anchor_rating.png),
а цифры читаем в фиксированных областях относительно этой подписи.
Координаты заданы для клиента 1920×1080; другие 16:9 разрешения
масштабируются к нему.
"""
from __future__ import annotations

import re
from datetime import datetime

import cv2
import numpy as np
import pytesseract

from . import heroes
from .config import ASSETS_DIR

BASE_H = 1080
# Где искать подпись «Рейтинг» (x0, y0, x1, y1) в координатах 1920×1080.
SEARCH_BOX = (1050, 140, 1800, 330)
# Области относительно левого верхнего угла найденной подписи (dx0, dy0, dx1, dy1).
RATING_BOX = (-24, -33, 86, -5)
CONFIDENCE_BOX = (166, -29, 246, -7)
MATCH_THRESHOLD = 0.80

_anchor = cv2.imread(str(ASSETS_DIR / "anchor_rating.png"), cv2.IMREAD_GRAYSCALE)
if _anchor is None:
    raise RuntimeError("Не найден mmreon/assets/anchor_rating.png")


def set_tesseract(cmd: str) -> None:
    if cmd:
        pytesseract.pytesseract.tesseract_cmd = cmd


def _normalize(frame: np.ndarray) -> np.ndarray:
    h = frame.shape[0]
    if h == BASE_H:
        return frame
    scale = BASE_H / h
    return cv2.resize(frame, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)


def find_anchor(frame: np.ndarray):
    """Возвращает (x, y, score) подписи «Рейтинг» или None, если вкладка не открыта."""
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    x0, y0, x1, y1 = SEARCH_BOX
    region = gray[y0:y1, x0:x1]
    if region.shape[0] < _anchor.shape[0] or region.shape[1] < _anchor.shape[1]:
        return None
    res = cv2.matchTemplate(region, _anchor, cv2.TM_CCOEFF_NORMED)
    _, score, _, loc = cv2.minMaxLoc(res)
    if score < MATCH_THRESHOLD:
        return None
    return loc[0] + x0, loc[1] + y0, float(score)


def _crop(frame, ax, ay, box):
    dx0, dy0, dx1, dy1 = box
    return frame[max(ay + dy0, 0):ay + dy1, max(ax + dx0, 0):ax + dx1]


def _read_rating(crop) -> int | None:
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    g = cv2.resize(g, None, fx=4, fy=4, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    b = cv2.copyMakeBorder(b, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    txt = pytesseract.image_to_string(b, config="--psm 7 -c tessedit_char_whitelist=0123456789")
    digits = "".join(ch for ch in txt if ch.isdigit())
    if not digits:
        return None
    value = int(digits)
    return value if 0 < value < 20000 else None


def _read_confidence(crop) -> int | None:
    # Белый текст на золотой полосе: оставляем только почти белые пиксели.
    m = crop.astype(int).min(axis=2)
    b = np.where(m > 180, 0, 255).astype(np.uint8)
    b = cv2.resize(b, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST)
    b = cv2.copyMakeBorder(b, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=255)
    txt = pytesseract.image_to_string(b, config="--psm 7 -c tessedit_char_whitelist=0123456789%")
    digits = "".join(ch for ch in txt if ch.isdigit())
    if not digits:
        return None
    value = int(digits)
    return value if 0 <= value <= 100 else None


def locate(frame: np.ndarray):
    """(кадр 1080p, (ax, ay, score)) если вкладка «История» открыта, иначе None."""
    frame = _normalize(frame)
    found = find_anchor(frame)
    return (frame, found) if found else None


def read_rating(frame: np.ndarray, anchor) -> dict | None:
    ax, ay, score = anchor
    rating = _read_rating(_crop(frame, ax, ay, RATING_BOX))
    if rating is None:
        return None
    confidence = _read_confidence(_crop(frame, ax, ay, CONFIDENCE_BOX))
    return {"rating": rating, "confidence": confidence, "anchor_score": round(score, 3)}


def read(frame: np.ndarray) -> dict | None:
    """Читает рейтинг с кадра. None — вкладка не открыта или цифра не прочиталась."""
    loc = locate(frame)
    return read_rating(*loc) if loc else None


# ---------- таблица матчей на вкладке «История» ----------
#
# Строки идут с шагом 36 px, первая — на 91 px ниже подписи «Рейтинг».
# Колонки заданы смещением по x от подписи (x0, x1).
ROW0_DY, ROW_STEP, ROWS, ROW_HALF = 91, 36, 18, 12
COL_HERO = (-918, -694)
COL_RESULT = (-682, -574)
COL_DATETIME = (-432, -279)   # «25.10.2026  18:14»
COL_DURATION = (-134, -40)
COL_TYPE = (66, 206)

_type_templates = {}
for _mode, _file in (("ranked", "type_ranked.png"), ("turbo", "type_turbo.png")):
    _t = cv2.imread(str(ASSETS_DIR / _file), cv2.IMREAD_GRAYSCALE)
    if _t is not None:
        _type_templates[_mode] = _t


def _column(frame, anchor, col):
    ax, ay, _ = anchor
    y0 = ay + ROW0_DY - ROW_HALF
    y1 = ay + ROW0_DY + ROW_STEP * (ROWS - 1) + ROW_HALF
    return frame[max(y0, 0):y1, max(ax + col[0], 0):ax + col[1]], y0


def _column_lines(frame, anchor, col, whitelist=None) -> dict:
    """Читает колонку целиком (один вызов Tesseract) и раскладывает строки по номерам."""
    crop, y0 = _column(frame, anchor, col)
    if crop.size == 0:
        return {}
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = 3
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    pad = 20
    b = cv2.copyMakeBorder(b, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    cfg = "--psm 6" + (f" -c tessedit_char_whitelist={whitelist}" if whitelist else "")
    data = pytesseract.image_to_data(b, config=cfg, output_type=pytesseract.Output.DICT)
    rows: dict[int, list] = {}
    for i, word in enumerate(data["text"]):
        word = word.strip()
        if not word:
            continue
        cy = (data["top"][i] + data["height"][i] / 2 - pad) / scale     # от верха колонки
        row = int(round((cy - ROW_HALF) / ROW_STEP))
        if 0 <= row < ROWS:
            rows.setdefault(row, []).append((data["left"][i], word))
    return {r: " ".join(w for _, w in sorted(ws)) for r, ws in rows.items()}


def _row_cell(frame, anchor, row, col):
    ax, ay, _ = anchor
    cy = ay + ROW0_DY + ROW_STEP * row
    return frame[cy - ROW_HALF:cy + ROW_HALF, ax + col[0]:ax + col[1]]


def _result(cell) -> bool | None:
    """Победа — зелёный текст, поражение — красный."""
    px = cell.reshape(-1, 3).astype(int)
    bright = px[px.max(axis=1) > 90]
    if len(bright) < 15:
        return None
    b, g, r = bright.mean(axis=0)
    if g > r * 1.2:
        return True
    if r > g * 1.2:
        return False
    return None


def _mode(cell) -> str | None:
    g = cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY)
    if (g > 120).sum() < 10:
        return None
    best, score = "other", 0.0
    for mode, tpl in _type_templates.items():
        if g.shape[0] < tpl.shape[0] or g.shape[1] < tpl.shape[1]:
            continue
        s = cv2.minMaxLoc(cv2.matchTemplate(g, tpl, cv2.TM_CCOEFF_NORMED))[1]
        if s > score:
            best, score = mode, s
    return best if score >= 0.8 else "other"


def _duration(text: str) -> int | None:
    parts = [p for p in re.split(r"[^0-9]+", text) if p]
    if len(parts) == 2:
        m, s = map(int, parts)
        return m * 60 + s if s < 60 else None
    if len(parts) == 3:
        h, m, s = map(int, parts)
        return h * 3600 + m * 60 + s if m < 60 and s < 60 else None
    return None


def _datetime(text: str) -> datetime | None:
    m = re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})\D+(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    d, mo, y, h, mi = map(int, m.groups())
    try:
        return datetime(y, mo, d, h, mi)
    except ValueError:
        return None


def table_signature(frame, anchor) -> bytes:
    """Короткий отпечаток таблицы: меняется, когда в ней что-то поменялось."""
    crop, _ = _column(frame, anchor, (COL_HERO[0], COL_TYPE[1]))
    small = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (64, 48), interpolation=cv2.INTER_AREA)
    return (small // 32).tobytes()


def read_history(frame, anchor) -> list[dict]:
    """Строки таблицы: герой, результат, начало, длительность, тип игры."""
    heroes_txt = _column_lines(frame, anchor, COL_HERO)
    dt_txt = _column_lines(frame, anchor, COL_DATETIME, "0123456789.:")
    dur_txt = _column_lines(frame, anchor, COL_DURATION, "0123456789:")
    rows = []
    for i in range(ROWS):
        started = _datetime(dt_txt.get(i, ""))
        hero = heroes.code_from_text(heroes_txt.get(i, ""))
        if not started or not hero:
            continue
        rows.append({
            "row": i,
            "hero": hero,
            "won": _result(_row_cell(frame, anchor, i, COL_RESULT)),
            "started": started,
            "duration_sec": _duration(dur_txt.get(i, "")),
            "mode": _mode(_row_cell(frame, anchor, i, COL_TYPE)),
        })
    return rows
