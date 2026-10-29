"""Распознавание рейтинга и уверенности в ранге с вкладки «Профиль → История».

Вкладку узнаём по золотой подписи «Рейтинг» (assets/anchor_rating.png),
а цифры читаем в фиксированных областях относительно этой подписи.
Координаты заданы для клиента 1920×1080; другие 16:9 разрешения
масштабируются к нему.
"""
from __future__ import annotations

import cv2
import numpy as np
import pytesseract

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


def read(frame: np.ndarray) -> dict | None:
    """Читает рейтинг с кадра. None — вкладка не открыта или цифра не прочиталась."""
    frame = _normalize(frame)
    found = find_anchor(frame)
    if not found:
        return None
    ax, ay, score = found
    rating = _read_rating(_crop(frame, ax, ay, RATING_BOX))
    if rating is None:
        return None
    confidence = _read_confidence(_crop(frame, ax, ay, CONFIDENCE_BOX))
    return {"rating": rating, "confidence": confidence, "anchor_score": round(score, 3)}
