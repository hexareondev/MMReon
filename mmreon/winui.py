"""Оформление окон средствами Windows: иконка, тёмная рамка, прозрачность виджета.

pywebview на Windows не умеет ставить иконку окна и красить заголовок,
поэтому делаем это напрямую через WinAPI. На других системах функции ничего не делают.
"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

IS_WIN = os.name == "nt"
_icons = []   # держим ссылки на загруженные иконки, пока жива программа

if IS_WIN:
    user32 = ctypes.windll.user32
    user32.FindWindowW.restype = wintypes.HWND
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.LoadImageW.restype = wintypes.HANDLE
    user32.LoadImageW.argtypes = [wintypes.HINSTANCE, wintypes.LPCWSTR, wintypes.UINT,
                                  ctypes.c_int, ctypes.c_int, wintypes.UINT]
    user32.SendMessageW.restype = wintypes.LPARAM
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.GetWindowLongW.restype = ctypes.c_long
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetWindowLongW.restype = ctypes.c_long
    user32.SetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_long]
    user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
    user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                                    ctypes.c_int, ctypes.c_int, wintypes.UINT]


def find(title: str):
    return user32.FindWindowW(None, title) if IS_WIN else None


def set_app_id(app_id: str) -> None:
    """Своя группа на панели задач — тогда там показывается наша иконка, а не значок Python."""
    if IS_WIN:
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        except Exception:
            pass


def set_icon(title: str, ico_path) -> bool:
    hwnd = find(title)
    if not hwnd:
        return False
    LR_LOADFROMFILE, IMAGE_ICON, WM_SETICON = 0x10, 1, 0x80
    for kind, (mx, my) in ((1, (11, 12)), (0, (49, 50))):   # ICON_BIG: SM_CXICON; ICON_SMALL: SM_CXSMICON
        icon = user32.LoadImageW(None, str(ico_path), IMAGE_ICON,
                                 user32.GetSystemMetrics(mx), user32.GetSystemMetrics(my), LR_LOADFROMFILE)
        if icon:
            _icons.append(icon)
            user32.SendMessageW(hwnd, WM_SETICON, kind, icon)
    return True


def _rgb(hex_color: str) -> int:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return r | (g << 8) | (b << 16)


def dark_frame(title: str, caption: str = "#12151C", text: str = "#ECE7DE", border: str = "#2C3240") -> bool:
    """Тёмный системный заголовок. Цвет заголовка и рамки — только Windows 11, на 10 просто тёмный."""
    hwnd = find(title)
    if not hwnd:
        return False
    dwm = ctypes.windll.dwmapi
    on = ctypes.c_int(1)
    for attr in (20, 19):   # DWMWA_USE_IMMERSIVE_DARK_MODE (новые и старые сборки Windows 10)
        if dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(on), ctypes.sizeof(on)) == 0:
            break
    for attr, color in ((35, caption), (36, text), (34, border)):   # CAPTION / TEXT / BORDER_COLOR
        val = ctypes.c_uint(_rgb(color))
        dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), ctypes.sizeof(val))
    # Перерисовать рамку, иначе новый цвет появится только после смены фокуса.
    user32.SetWindowPos(hwnd, None, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0004 | 0x0020)
    return True


def set_opacity(title: str, value: float) -> bool:
    """Прозрачность всего окна целиком (0.3–1.0)."""
    hwnd = find(title)
    if not hwnd:
        return False
    GWL_EXSTYLE, WS_EX_LAYERED, LWA_ALPHA = -20, 0x00080000, 0x2
    style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if value >= 0.995:
        if style & WS_EX_LAYERED:
            user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style & ~WS_EX_LAYERED)
        return True
    if not style & WS_EX_LAYERED:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_LAYERED)
    alpha = max(77, min(255, int(round(value * 255))))
    user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
    return True
