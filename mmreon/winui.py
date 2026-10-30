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


def set_form_icon(window, ico_path) -> bool:
    """Иконка через само окно WinForms, которым pywebview управляет на Windows.

    Сообщение WM_SETICON pywebview может перезаписать своей иконкой (значок Python),
    а свойство Form.Icon он уже не трогает. Оно же даёт иконку на панели задач.
    """
    if not IS_WIN:
        return False
    try:
        import clr  # noqa: F401  (pythonnet, приходит вместе с pywebview)
        from System import Action
        from System.Drawing import Icon

        form = getattr(window, "native", None)
        if form is None:
            return False
        icon = Icon(str(ico_path))
        _icons.append(icon)

        def apply():
            form.Icon = icon
            form.ShowIcon = True

        if form.InvokeRequired:
            form.Invoke(Action(apply))
        else:
            apply()
        return True
    except Exception:
        return False


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


GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020      # клики проходят сквозь окно
WS_EX_TOOLWINDOW = 0x00000080       # нет кнопки на панели задач и в Alt+Tab
WS_EX_APPWINDOW = 0x00040000
WS_EX_LAYERED = 0x00080000          # нужен для прозрачности и пропуска кликов
WS_EX_NOACTIVATE = 0x08000000       # не забирает фокус у игры
LWA_ALPHA = 0x2


def overlay_style(title: str, click_through: bool, opacity: float) -> bool:
    """Делает виджет оверлеем: без панели задач и Alt+Tab, без фокуса, при желании — сквозной для кликов."""
    hwnd = find(title)
    if not hwnd:
        return False
    ex = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    new = (ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE) & ~WS_EX_APPWINDOW
    layered = click_through or opacity < 0.995
    new = (new | WS_EX_TRANSPARENT) if click_through else (new & ~WS_EX_TRANSPARENT)
    new = (new | WS_EX_LAYERED) if layered else (new & ~WS_EX_LAYERED)
    if new != ex:
        user32.SetWindowLongW(hwnd, GWL_EXSTYLE, ctypes.c_long(new & 0xFFFFFFFF).value)
    if layered:
        alpha = max(77, min(255, int(round(opacity * 255))))
        user32.SetLayeredWindowAttributes(hwnd, 0, alpha, LWA_ALPHA)
    return True


def place(title: str, x: int, y: int, w: int, h: int) -> bool:
    """Ставит окно поверх остальных точно в указанный прямоугольник (физические пиксели)."""
    hwnd = find(title)
    if not hwnd:
        return False
    HWND_TOPMOST = wintypes.HWND(-1)
    SWP_NOACTIVATE = 0x0010
    user32.SetWindowPos(hwnd, HWND_TOPMOST, int(x), int(y), int(w), int(h), SWP_NOACTIVATE)
    return True
