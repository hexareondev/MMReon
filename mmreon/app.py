"""Окна MMReon на pywebview: главное окно со сводкой, виджет для главного меню Доты, значок в трее."""
from __future__ import annotations

import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

import webview

from . import __version__, config, shortcuts, state, updater, winui
from .heroes import name as hero_name
from .screen import WINDOW_TITLE, dota_client_rect, window_status
from .tray import Tray

UI_DIR = Path(__file__).resolve().parent / "ui"
ICON = Path(__file__).resolve().parent / "assets" / "mmreon.ico"
MAIN_TITLE = "MMReon"
WIDGET_TITLE = "MMReon · виджет"
WIDGET_SIZE = (366, 74)
# Панель профиля в главном меню Доты в координатах клиента 1920×1080.
# Левая колонка Доты привязана к левому краю и масштабируется по высоте окна.
PROFILE_PANEL = (33, 100, 366, 74)


def profile_panel_rect(rect):
    """Прямоугольник панели профиля на экране по клиентской области окна Доты."""
    left, top, _, height = rect
    s = height / 1080
    x, y, w, h = PROFILE_PANEL
    return left + round(x * s), top + round(y * s), round(w * s), round(h * s)


class Api:
    """Методы, доступные из JavaScript как window.pywebview.api.*"""

    def __init__(self, app: "App"):
        self._app = app

    def get_state(self):
        st = state.build(self._app.tracker, self._app.dota_running)
        st["update"] = self._app.update_info
        st["version"] = __version__
        return st

    def toggle_double(self, match_id):
        return self._app.tracker.toggle_double(str(match_id))

    def show_main(self):
        self._app.show_main()

    def get_settings(self):
        app, cfg = self._app, self._app.cfg
        return {"widget_enabled": cfg.get("widget_enabled", True),
                "widget_opacity": cfg.get("widget_opacity", 1.0),
                "widget_anchor": cfg.get("widget_anchor", True),
                "notifications": cfg.get("notifications", True),
                "close_to_tray": cfg.get("close_to_tray", True),
                "autostart": app.autostart_enabled(),
                "tray": app.tray_active}

    def set_widget_enabled(self, enabled):
        self._app.set_widget_enabled(enabled)

    def set_widget_opacity(self, value):
        self._app.cfg["widget_opacity"] = max(0.3, min(1.0, float(value)))
        config.save(self._app.cfg)
        self._app.apply_widget_style()

    def set_widget_anchor(self, anchored):
        self._app.cfg["widget_anchor"] = bool(anchored)
        config.save(self._app.cfg)
        self._app.apply_widget_style()
        self._app.reposition_widget(force=True)

    def set_notifications(self, enabled):
        self._app.set_notifications(enabled)

    def set_close_to_tray(self, enabled):
        self._app.cfg["close_to_tray"] = bool(enabled)
        config.save(self._app.cfg)

    def set_autostart(self, enabled):
        return self._app.set_autostart(enabled)

    def set_goal(self, rating, date=None):
        return self._app.set_goal(rating, date)

    def clear_goal(self):
        return self._app.set_goal(None)

    def check_updates(self):
        return self._app.check_updates()

    def apply_update(self):
        return self._app.apply_update()

    def open_url(self, url):
        if str(url).startswith("https://"):
            webbrowser.open(url)

    def quit(self):
        self._app.quit()


class App:
    def __init__(self, tracker, cfg: dict):
        self.tracker = tracker
        self.cfg = cfg
        self.dota_running = False
        self.quitting = False
        self.restart_requested = False
        self.update_info = None
        self.tray = Tray(self)
        self.tray_active = False
        self._autostart = None
        self._widget_visible = False
        self._widget_rect = None
        self._stop = threading.Event()
        tracker.on_rated = self._on_rated
        api = Api(self)
        self.main = webview.create_window(
            MAIN_TITLE, str(UI_DIR / "main.html"), js_api=api,
            width=1180, height=860, min_size=(760, 560), background_color="#12151C")
        self.widget = webview.create_window(
            WIDGET_TITLE, str(UI_DIR / "widget.html"), js_api=api,
            width=WIDGET_SIZE[0], height=WIDGET_SIZE[1],
            min_size=(40, 20),      # по умолчанию pywebview не даёт окну быть ниже 100 px
            x=cfg.get("widget_x", 24), y=cfg.get("widget_y", 120),
            frameless=True, easy_drag=True, resizable=False, on_top=True,
            focus=False, hidden=True, background_color="#12151C")
        self.main.events.closing += self._on_main_closing
        minimized = getattr(self.main.events, "minimized", None)
        if minimized is not None:
            minimized += self._on_main_minimized
        moved = getattr(self.widget.events, "moved", None)
        if moved is not None:
            moved += self._on_widget_moved

    # ---------- окно и трей ----------

    def _on_main_closing(self):
        # С треем крестик прячет окно; без трея (или если так настроено) — выход.
        if not self.quitting and self.tray_active and self.cfg.get("close_to_tray", True):
            self.main.hide()
            return False
        if not self.quitting:
            self.quitting = True
            self._stop.set()
            self.tray.stop()
            threading.Thread(target=self._destroy_widget, daemon=True).start()
        return True

    def _on_main_minimized(self):
        if self.tray_active and not self.quitting:
            self.main.hide()      # свёрнутое окно живёт в трее, а не на панели задач

    def _destroy_widget(self):
        try:
            self.widget.destroy()
        except Exception:
            pass

    def show_main(self):
        self.main.show()
        self.main.restore()

    def quit(self):
        self.quitting = True
        self._stop.set()
        self.tray.stop()
        for w in (self.widget, self.main):
            try:
                w.destroy()
            except Exception:
                pass

    # ---------- настройки ----------

    def widget_enabled(self) -> bool:
        return bool(self.cfg.get("widget_enabled", True))

    def set_widget_enabled(self, enabled):
        self.cfg["widget_enabled"] = bool(enabled)
        config.save(self.cfg)
        self.tray.refresh()

    def notifications_enabled(self) -> bool:
        return bool(self.cfg.get("notifications", True))

    def set_notifications(self, enabled):
        self.cfg["notifications"] = bool(enabled)
        config.save(self.cfg)
        self.tray.refresh()

    def autostart_enabled(self) -> bool:
        if self._autostart is None:
            try:
                self._autostart = shortcuts.autostart_enabled()
            except Exception:
                self._autostart = False
        return self._autostart

    def set_autostart(self, enabled) -> bool:
        ok = shortcuts.set_autostart(bool(enabled))
        self._autostart = None
        self.tray.refresh()
        return ok and self.autostart_enabled() == bool(enabled)

    def set_goal(self, rating, date=None):
        if rating in (None, "", 0):
            self.cfg["goal"] = None
        else:
            current = (self.tracker.store.rating or {}).get("value")
            self.cfg["goal"] = {"rating": int(rating), "date": date or None,
                                "start": current, "set_at": datetime.now().astimezone().isoformat(timespec="seconds")}
        config.save(self.cfg)
        return self.cfg["goal"]

    # ---------- уведомления ----------

    def _on_rated(self, match: dict, before: int | None, after: int):
        if not self.notifications_enabled():
            return
        hero = hero_name(match.get("hero"))
        result = "Победа" if match.get("won") else "Поражение"
        if match["status"] == "exact":
            delta = match["delta"]
            line = f"{'+' if delta > 0 else ''}{delta} · рейтинг {after}"
            m_before, m_after = state.medal(before), state.medal(after)
            if m_before and m_after and m_before["name"] != m_after["name"]:
                line += f" · {m_before['name']} → {m_after['name']}"
            if match.get("double"):
                line += " · жетон ×2"
        elif match["status"] == "unrated":
            line = "Рейтинг не изменился — нерейтинговая игра"
        else:
            line = f"Рейтинг {after}"
        self.tray.notify(f"{result} · {hero}", line)

    # ---------- обновления ----------

    def check_updates(self):
        self.update_info = updater.check()
        self.update_info["checked_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
        return self.update_info

    def apply_update(self):
        res = updater.apply()
        if res.get("ok"):
            self.restart_requested = True
            threading.Timer(1.5, self.quit).start()   # дать окну показать сообщение
        return res

    def _check_updates_later(self):
        time.sleep(20)          # не мешаем запуску
        try:
            self.check_updates()
            info = self.update_info
            if info.get("available"):
                self.tray.notify("Доступно обновление MMReon", "Откройте окно, чтобы обновить одной кнопкой")
        except Exception:
            pass

    # ---------- виджет ----------

    def _on_widget_moved(self, x, y):
        if self.cfg.get("widget_anchor", True):
            return      # закреплённый виджет двигаем сами
        self.cfg["widget_x"], self.cfg["widget_y"] = int(x), int(y)
        config.save(self.cfg)

    def apply_widget_style(self):
        """Оверлей: без панели задач и фокуса. Закреплённый — ещё и пропускает клики в Доту."""
        winui.overlay_style(WIDGET_TITLE,
                            click_through=self.cfg.get("widget_anchor", True),
                            opacity=self.cfg.get("widget_opacity", 1.0))

    def reposition_widget(self, force=False):
        if self.cfg.get("widget_anchor", True):
            rect = dota_client_rect(require_foreground=False)
            if not rect:
                return
            target = profile_panel_rect(rect)
        else:
            target = (self.cfg.get("widget_x", 24), self.cfg.get("widget_y", 120), *WIDGET_SIZE)
            if not force:
                return  # свободный виджет пользователь двигает сам
        if force or target != self._widget_rect:
            winui.place(WIDGET_TITLE, *target)
            self._widget_rect = target

    def _widget_loop(self):
        """Виджет виден в главном меню Доты и прячется на время матча."""
        while not self._stop.wait(1.0):
            st = window_status()
            self.dota_running = st["running"]
            ours = st["foreground_title"] in (WIDGET_TITLE, MAIN_TITLE)
            dota_active = st["foreground_title"] == WINDOW_TITLE
            want = (self.widget_enabled() and st["running"] and not st["minimized"]
                    and not self.tracker.in_match and (dota_active or ours))
            try:
                if want != self._widget_visible:
                    if want:
                        self.apply_widget_style()
                        self.widget.show()
                        self.apply_widget_style()
                        self.reposition_widget(force=True)
                    else:
                        self.widget.hide()
                    self._widget_visible = want
                elif want:
                    self.reposition_widget()    # Дота могла сменить размер или положение окна
            except Exception:
                pass

    # ---------- запуск ----------

    def _decorate(self):
        """Иконка и тёмная рамка — как только Windows создаст окна."""
        for _ in range(50):
            if winui.find(MAIN_TITLE) and getattr(self.main, "native", None) is not None:
                break
            time.sleep(0.1)
        winui.dark_frame(MAIN_TITLE)
        for window, title in ((self.main, MAIN_TITLE), (self.widget, WIDGET_TITLE)):
            if not winui.set_form_icon(window, ICON):
                winui.set_icon(title, ICON)
        self.apply_widget_style()   # пока виджет скрыт — тогда он сразу появится без кнопки на панели задач

    def run(self, start_hidden=False):
        winui.set_app_id("hexareon.mmreon")
        self.tray_active = self.tray.start()

        def started():
            threading.Thread(target=self._decorate, daemon=True, name="decorate").start()
            threading.Thread(target=self._widget_loop, daemon=True, name="widget").start()
            threading.Thread(target=self._check_updates_later, daemon=True, name="updates").start()
            if start_hidden and self.tray_active:
                time.sleep(0.5)
                self.main.hide()
        webview.start(started)
