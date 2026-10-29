"""Окна MMReon на pywebview: главное окно со сводкой и виджет для главного меню Доты."""
from __future__ import annotations

import threading
from pathlib import Path

import webview

from . import config, state
from .screen import WINDOW_TITLE, window_status

UI_DIR = Path(__file__).resolve().parent / "ui"
MAIN_TITLE = "MMReon"
WIDGET_TITLE = "MMReon · виджет"
WIDGET_SIZE = (340, 64)


class Api:
    """Методы, доступные из JavaScript как window.pywebview.api.*"""

    def __init__(self, app: "App"):
        self._app = app

    def get_state(self):
        return state.build(self._app.tracker, self._app.dota_running)

    def toggle_double(self, match_id):
        return self._app.tracker.toggle_double(str(match_id))

    def show_main(self):
        self._app.show_main()

    def minimize(self):
        self._app.main.minimize()

    def get_settings(self):
        return {"widget_enabled": self._app.cfg.get("widget_enabled", True)}

    def set_widget_enabled(self, enabled):
        self._app.cfg["widget_enabled"] = bool(enabled)
        config.save(self._app.cfg)

    def quit(self):
        self._app.quit()


class App:
    def __init__(self, tracker, cfg: dict):
        self.tracker = tracker
        self.cfg = cfg
        self.dota_running = False
        self.quitting = False
        self._widget_visible = False
        self._stop = threading.Event()
        api = Api(self)
        self.main = webview.create_window(
            MAIN_TITLE, str(UI_DIR / "main.html"), js_api=api,
            width=1180, height=860, min_size=(760, 560), background_color="#0E1014",
            frameless=True, easy_drag=False)   # своя полоса заголовка в main.html
        self.widget = webview.create_window(
            WIDGET_TITLE, str(UI_DIR / "widget.html"), js_api=api,
            width=WIDGET_SIZE[0], height=WIDGET_SIZE[1],
            x=cfg.get("widget_x", 24), y=cfg.get("widget_y", 120),
            frameless=True, easy_drag=True, resizable=False, on_top=True,
            focus=False, hidden=True, background_color="#0E1014")
        self.main.events.closing += self._on_main_closing
        moved = getattr(self.widget.events, "moved", None)
        if moved is not None:
            moved += self._on_widget_moved

    # Закрытие главного окна (× или Alt+F4) — выход из MMReon. Для работы в фоне окно сворачивают.
    def _on_main_closing(self):
        if not self.quitting:
            self.quitting = True
            self._stop.set()
            threading.Thread(target=self._destroy_widget, daemon=True).start()
        return True

    def _destroy_widget(self):
        try:
            self.widget.destroy()
        except Exception:
            pass

    def _on_widget_moved(self, x, y):
        self.cfg["widget_x"], self.cfg["widget_y"] = int(x), int(y)
        config.save(self.cfg)

    def show_main(self):
        self.main.restore()
        self.main.show()

    def quit(self):
        self.quitting = True
        self._stop.set()
        for w in (self.widget, self.main):
            try:
                w.destroy()
            except Exception:
                pass

    def _widget_loop(self):
        """Виджет виден в главном меню Доты и прячется на время матча."""
        while not self._stop.wait(1.0):
            st = window_status()
            self.dota_running = st["running"]
            ours = st["foreground_title"] in (WIDGET_TITLE, MAIN_TITLE)
            dota_active = st["foreground_title"] == WINDOW_TITLE
            want = (self.cfg.get("widget_enabled", True) and st["running"] and not st["minimized"]
                    and not self.tracker.in_match and (dota_active or ours))
            if want != self._widget_visible:
                try:
                    self.widget.show() if want else self.widget.hide()
                    self._widget_visible = want
                except Exception:
                    pass

    def run(self, on_started=None):
        def started():
            threading.Thread(target=self._widget_loop, daemon=True, name="widget").start()
            if on_started:
                on_started()
        webview.start(started)
