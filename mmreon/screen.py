"""Снимок клиентской области окна Dota 2 (только Windows).

Снимаем окно только когда оно активно (на переднем плане), чтобы не читать
чужие окна и не тратить ресурсы, пока Дота свёрнута.
"""
from __future__ import annotations

import ctypes
import os

import numpy as np

WINDOW_TITLE = "Dota 2"
_dpi_set = False


def _ensure_dpi_awareness():
    global _dpi_set
    if _dpi_set or os.name != "nt":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass
    _dpi_set = True


class _RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


class _POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def window_status() -> dict:
    """Есть ли окно Доты, свёрнуто ли оно и какое окно сейчас активно."""
    if os.name != "nt":
        return {"running": False, "minimized": False, "foreground_title": ""}
    _ensure_dpi_awareness()
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    fg = user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(fg, buf, 256)
    return {
        "running": bool(hwnd),
        "minimized": bool(hwnd) and bool(user32.IsIconic(hwnd)),
        "foreground_title": buf.value,
    }


def dota_client_rect():
    """(left, top, width, height) клиентской области Доты, если она активное окно."""
    if os.name != "nt":
        return None
    _ensure_dpi_awareness()
    user32 = ctypes.windll.user32
    hwnd = user32.FindWindowW(None, WINDOW_TITLE)
    if not hwnd or user32.GetForegroundWindow() != hwnd:
        return None
    rect = _RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    origin = _POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(origin))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    return origin.x, origin.y, w, h


class Grabber:
    """Держит один экземпляр mss на поток."""

    def __init__(self):
        import mss
        self._sct = mss.mss()

    def grab(self) -> np.ndarray | None:
        rect = dota_client_rect()
        if not rect:
            return None
        left, top, w, h = rect
        shot = self._sct.grab({"left": left, "top": top, "width": w, "height": h})
        return np.ascontiguousarray(np.array(shot)[:, :, :3])  # BGRA -> BGR


def looks_black(frame: np.ndarray) -> bool:
    """Полноэкранный режим часто отдаёт чёрный кадр."""
    return float(frame.mean()) < 3.0
