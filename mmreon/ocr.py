"""Распознавание рейтинга и уверенности в ранге с вкладки «Профиль → История».

Вкладку узнаём по золотой подписи «Рейтинг» (assets/anchor_rating.png),
а цифры читаем в фиксированных областях относительно этой подписи.
Координаты заданы для клиента 1920×1080; другие 16:9 разрешения
масштабируются к нему.
"""
from __future__ import annotations

import os
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


class _HiddenSubprocess:
    """subprocess для pytesseract, у которого любой запуск Tesseract идёт без консольного окна.

    Обычные вызовы pytesseract прячет сам, а проверку версии (`tesseract --version`,
    один раз при первом чтении таблицы «Истории») — нет: из программы без консоли
    на секунду мелькало чёрное окно.
    """
    CREATE_NO_WINDOW = 0x08000000

    def __init__(self, real):
        self._real = real

    def __getattr__(self, name):
        return getattr(self._real, name)

    def _hide(self, kwargs):
        kwargs["creationflags"] = kwargs.get("creationflags", 0) | self.CREATE_NO_WINDOW
        return kwargs

    def Popen(self, *args, **kwargs):
        return self._real.Popen(*args, **self._hide(kwargs))

    def check_output(self, *args, **kwargs):
        return self._real.check_output(*args, **self._hide(kwargs))

    def run(self, *args, **kwargs):
        return self._real.run(*args, **self._hide(kwargs))


if os.name == "nt" and not isinstance(pytesseract.pytesseract.subprocess, _HiddenSubprocess):
    pytesseract.pytesseract.subprocess = _HiddenSubprocess(pytesseract.pytesseract.subprocess)


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
HISTORY = {"dy": ROW0_DY, "step": ROW_STEP, "rows": ROWS, "half": ROW_HALF}
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


def _column(frame, anchor, col, geo=HISTORY):
    ax, ay, _ = anchor
    y0 = ay + geo["dy"] - geo["half"]
    y1 = ay + geo["dy"] + geo["step"] * (geo["rows"] - 1) + geo["half"]
    return frame[max(y0, 0):y1, max(ax + col[0], 0):ax + col[1]], y0


def _column_lines(frame, anchor, col, whitelist=None, geo=HISTORY) -> dict:
    """Читает колонку целиком (один вызов Tesseract) и раскладывает строки по номерам."""
    crop, y0 = _column(frame, anchor, col, geo)
    if crop.size == 0:
        return {}
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    scale = 3
    g = cv2.resize(g, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    # Порог Оцу на почти чёрной таблице уходит слишком низко, и серый фон строки под курсором
    # сливается с цифрами («15:57» читалось как «18:57»). Текст светлый (~190), фон подсветки ~30 —
    # поэтому порог не ниже 100.
    otsu, _ = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    _, b = cv2.threshold(g, max(otsu, 100), 255, cv2.THRESH_BINARY_INV)
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
        row = int(round((cy - geo["half"]) / geo["step"]))
        if 0 <= row < geo["rows"]:
            rows.setdefault(row, []).append((data["left"][i], word))
    return {r: " ".join(w for _, w in sorted(ws)) for r, ws in rows.items()}


def _row_cell(frame, anchor, row, col, geo=HISTORY):
    ax, ay, _ = anchor
    cy = ay + geo["dy"] + geo["step"] * row
    return frame[cy - geo["half"]:cy + geo["half"], ax + col[0]:ax + col[1]]


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
    # Между датой и временем пробел иногда пропадает: «11.11.202620:33» — год всегда 4 цифры.
    m = re.search(r"(\d{1,3})\.(\d{1,2})\.(\d{4})\D*(\d{1,2}):(\d{2})", text)
    if not m:
        return None
    day_txt, mo, y, h, mi = m.group(1), *map(int, m.groups()[1:])
    # У края столбца первая цифра иногда двоится: «77.11» вместо «7.11». Лишнее отбрасываем.
    d = int(day_txt[-2:]) if 1 <= int(day_txt[-2:]) <= 31 else int(day_txt[-1])
    try:
        return datetime(y, mo, d, h, mi)
    except ValueError:
        return None


HOVER_STRIPS = ((-585, -445), (-263, -143))     # пустые промежутки между колонками «Истории»


def _hovered_row(frame, anchor, strips, geo=HISTORY) -> int | None:
    """Строка под курсором: игра подсвечивает её фон (~30 против 1–14 у соседних строк).
    Текст на подсветке читается с ошибками («51:20» как «1:20», «15:57» как «18:57»),
    поэтому такую строку пропускаем — она прочитается, когда курсор уйдёт."""
    bg = []
    for i in range(geo["rows"]):
        vals = []
        for col in strips:
            cell = _row_cell(frame, anchor, i, col, geo)
            if cell.size:
                vals.append(float(np.median(cv2.cvtColor(cell, cv2.COLOR_BGR2GRAY))))
        bg.append(min(vals) if vals else None)
    best, best_lift = None, 0.0
    for i, v in enumerate(bg):
        if v is None:
            continue
        near = [bg[j] for j in (i - 1, i + 1) if 0 <= j < len(bg) and bg[j] is not None]
        if not near:
            continue
        lift = v - max(near)
        if lift > best_lift:
            best, best_lift = i, lift
    return best if best_lift >= 15 else None


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
    hovered = _hovered_row(frame, anchor, HOVER_STRIPS)
    rows = []
    for i in range(ROWS):
        if i == hovered:
            continue
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


# ---------- таблица «Боевая статистика → Игры» (Dota Plus) ----------
#
# Подпись «Рейтинг» на этой вкладке на том же месте, что и в «Истории», поэтому якорь общий.
# Строки идут с шагом 43 px, первая — на 86 px ниже подписи. Героя здесь нет текстом
# (только портрет), зато есть точное изменение рейтинга (ИР) за каждый матч.
DOTAPLUS = {"dy": 86, "step": 43, "rows": 15, "half": 12}
DP_DATETIME = (-787, -664)      # «11.11.2026 20:33»
DP_RESULT = (-499, -432)
DP_DURATION = (-429, -344)
DP_KDA = (-332, -234)
DP_DELTA = (246, 316)           # ИР: «-20», «26», «0»
DP_HEADER_AT = (-508, 41)       # заголовки «РЗЛТ  ДЛИТ» относительно подписи «Рейтинг»
DP_HOVER_STRIPS = ((-200, -60), (60, 200))

_dp_header = cv2.imread(str(ASSETS_DIR / "dotaplus_header.png"), cv2.IMREAD_GRAYSCALE)


def table_kind(frame, anchor) -> str:
    """'dotaplus' — открыта «Боевая статистика → Игры», иначе 'history'."""
    if _dp_header is None:
        return "history"
    ax, ay, _ = anchor
    x0, y0 = ax + DP_HEADER_AT[0] - 12, ay + DP_HEADER_AT[1] - 8
    h, w = _dp_header.shape
    region = cv2.cvtColor(frame[max(y0, 0):y0 + h + 16, max(x0, 0):x0 + w + 24], cv2.COLOR_BGR2GRAY)
    if region.shape[0] < h or region.shape[1] < w:
        return "history"
    score = cv2.minMaxLoc(cv2.matchTemplate(region, _dp_header, cv2.TM_CCOEFF_NORMED))[1]
    return "dotaplus" if score >= 0.8 else "history"


def dotaplus_signature(frame, anchor) -> bytes:
    crop, _ = _column(frame, anchor, (DP_DATETIME[0], DP_DELTA[1]), DOTAPLUS)
    small = cv2.resize(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY), (64, 48), interpolation=cv2.INTER_AREA)
    return (small // 32).tobytes()


def _read_kda(frame, anchor) -> dict:
    """У/С/П по строкам: {строка: (у, с, п)}.

    Косая черта в этом шрифте похожа на «1» («17 / 7 / 6» читалось как «17/716»), поэтому
    сначала находим черты на картинке — узкие наклонные штрихи выше цифр, — режем ячейку
    по ним и раздвигаем числа, а распознаём уже одни цифры, одним вызовом на весь столбец.
    """
    geo = DOTAPLUS
    crop, _ = _column(frame, anchor, DP_KDA, geo)
    if crop.size == 0:
        return {}
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    n, lab, stats, _ = cv2.connectedComponentsWithStats((g > 80).astype(np.uint8), connectivity=8)
    slashes: dict[int, list] = {}
    for k in range(1, n):
        x, y, w, h, _area = stats[k]
        if h < 10 or w > 5:
            continue
        ys, xs = np.where(lab == k)
        if xs[ys <= y + 2].mean() - xs[ys >= y + h - 3].mean() >= 2:      # верх правее низа — «/»
            row = int(round((y + h / 2 - geo["half"]) / geo["step"]))
            slashes.setdefault(row, []).append((x, x + w))
    gap, pieces = 24, {}
    for row, cuts in slashes.items():
        if len(cuts) != 2 or not 0 <= row < geo["rows"]:
            continue
        cuts.sort()
        y0 = row * geo["step"]
        band = g[y0:y0 + 2 * geo["half"]]
        bounds = [(0, cuts[0][0]), (cuts[0][1], cuts[1][0]), (cuts[1][1], band.shape[1])]
        pieces[row] = [band[:, a_:b_] for a_, b_ in bounds]
    if not pieces:
        return {}
    width = max(sum(p.shape[1] for p in ps) + 2 * gap for ps in pieces.values())
    canvas = np.zeros((g.shape[0], width), np.uint8)
    for row, ps in pieces.items():
        x, y0 = 0, row * geo["step"]
        for piece in ps:
            canvas[y0:y0 + piece.shape[0], x:x + piece.shape[1]] = piece
            x += piece.shape[1] + gap
    scale, pad = 3, 20
    big = cv2.resize(canvas, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    _, b = cv2.threshold(big, 100, 255, cv2.THRESH_BINARY_INV)
    b = cv2.copyMakeBorder(b, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=255)
    data = pytesseract.image_to_data(b, config="--psm 6 -c tessedit_char_whitelist=0123456789",
                                     output_type=pytesseract.Output.DICT)
    words: dict[int, list] = {}
    for i, word in enumerate(data["text"]):
        if word.strip().isdigit():
            cy = (data["top"][i] + data["height"][i] / 2 - pad) / scale
            words.setdefault(int(round((cy - geo["half"]) / geo["step"])), []).append((data["left"][i], int(word)))
    return {row: tuple(v for _, v in sorted(ws)) for row, ws in words.items() if len(ws) == 3}


def _delta(text: str) -> int | None:
    m = re.search(r"(-?)\s*(\d{1,3})", text.replace("−", "-"))
    if not m:
        return None
    value = int(m.group(2))
    return -value if m.group(1) else value


def read_dotaplus(frame, anchor) -> list[dict]:
    """Строки Dota Plus: начало, результат, длительность, У/С/П и изменение рейтинга."""
    dt_txt = _column_lines(frame, anchor, DP_DATETIME, "0123456789.:", DOTAPLUS)
    dur_txt = _column_lines(frame, anchor, DP_DURATION, "0123456789:", DOTAPLUS)
    kda = _read_kda(frame, anchor)
    delta_txt = _column_lines(frame, anchor, DP_DELTA, "0123456789-", DOTAPLUS)
    hovered = _hovered_row(frame, anchor, DP_HOVER_STRIPS, DOTAPLUS)
    rows = []
    for i in range(DOTAPLUS["rows"]):
        if i == hovered:
            continue
        started = _datetime(dt_txt.get(i, ""))
        duration = _duration(dur_txt.get(i, ""))
        if not started or duration is None:
            continue
        k, d, a = kda.get(i, (None, None, None))
        rows.append({
            "row": i,
            "started": started,
            "won": _result(_row_cell(frame, anchor, i, DP_RESULT, DOTAPLUS)),
            "duration_sec": duration,
            "kills": k, "deaths": d, "assists": a,
            "delta": _delta(delta_txt.get(i, "")),
        })
    return rows
