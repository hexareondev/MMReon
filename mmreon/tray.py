"""Значок MMReon в трее (области уведомлений) и всплывающие уведомления Windows."""
from __future__ import annotations

from .config import ASSETS_DIR


class Tray:
    def __init__(self, app):
        self.app = app
        self.icon = None

    def start(self) -> bool:
        """Запускает значок. False — если pystray недоступен: тогда MMReon работает без трея."""
        try:
            import pystray
            from PIL import Image
        except Exception:
            return False
        app = self.app
        item = pystray.MenuItem
        menu = pystray.Menu(
            item("Открыть MMReon", lambda icon, it: app.show_main(), default=True),
            pystray.Menu.SEPARATOR,
            item("Виджет в главном меню Доты", lambda icon, it: app.set_widget_enabled(not app.widget_enabled()),
                 checked=lambda it: app.widget_enabled()),
            item("Уведомления после матча", lambda icon, it: app.set_notifications(not app.notifications_enabled()),
                 checked=lambda it: app.notifications_enabled()),
            item("Запускать вместе с Windows", lambda icon, it: app.set_autostart(not app.autostart_enabled()),
                 checked=lambda it: app.autostart_enabled()),
            pystray.Menu.SEPARATOR,
            item("Выйти из MMReon", lambda icon, it: app.quit()),
        )
        try:
            image = Image.open(ASSETS_DIR / "mmreon.png")
            self.icon = pystray.Icon("MMReon", image, "MMReon", menu)
            self.icon.run_detached()
            return True
        except Exception:
            self.icon = None
            return False

    def refresh(self):
        if self.icon:
            try:
                self.icon.update_menu()
            except Exception:
                pass

    def notify(self, title: str, message: str) -> bool:
        if not self.icon:
            return False
        try:
            self.icon.notify(message, title)
            return True
        except Exception:
            return False

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
            self.icon = None
