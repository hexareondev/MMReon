"""MMReon — запуск трекера.

    MMReon.pyw               — двойной клик: окно и виджет без консоли
    MMReon.pyw --tray        — сразу свернуть в трей (так запускает автозагрузка)
    python run.py            — то же, но с консолью (удобно для отладки)
    python run.py --no-ui    — только консоль
"""
import ctypes
import os
import sys
import threading
import time
from datetime import datetime

from mmreon import config, gsi_install, ocr
from mmreon.gsi import ask_running, start_server
from mmreon.screen import Grabber
from mmreon.store import Store
from mmreon.tracker import Tracker


def log(msg):
    print(f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


def fail(msg):
    """Ошибка запуска: в консоль, а без консоли — окном с сообщением."""
    log(msg)
    if os.name == "nt" and not (sys.stdout and getattr(sys.stdout, "isatty", lambda: False)()):
        ctypes.windll.user32.MessageBoxW(None, msg, "MMReon", 0x10)
    sys.exit(1)


def open_server(cfg, tracker, on_command, hidden: bool):
    """Занимает порт GSI. Если MMReon уже запущен — просит его показать окно и завершает эту копию."""
    port, token = cfg["gsi_port"], cfg["gsi_token"]
    try:
        return start_server(port, token, tracker.on_gsi, on_command)
    except OSError:
        pass
    if os.name == "nt":
        ctypes.windll.user32.AllowSetForegroundWindow(-1)   # разрешаем первой копии выйти на передний план
    answer = ask_running(port, token, "ping" if hidden else "show")
    if answer == "ok":
        log("MMReon уже запущен — открываю его окно, эта копия закрывается")
        sys.exit(0)
    if answer == "other_copy":
        fail("Уже запущена другая копия MMReon — из другой папки. "
             "Закройте её через значок в трее («Выйти из MMReon») и запустите эту снова.")
    for _ in range(5):          # после обновления старая копия может ещё закрываться
        time.sleep(1)
        try:
            return start_server(port, token, tracker.on_gsi, on_command)
        except OSError:
            pass
    fail(f"Порт {port} занят другой программой, поэтому MMReon не может принимать данные от Доты. "
         f"Поменяйте gsi_port в data\\config.json и перезапустите MMReon.")


def main():
    no_ui = "--no-ui" in sys.argv
    hidden = "--tray" in sys.argv
    cfg = config.load()
    ocr.set_tesseract(cfg["tesseract_cmd"])
    store = Store(config.MATCHES_PATH)

    local = threading.local()

    def grab():
        if not hasattr(local, "grabber"):
            local.grabber = Grabber()
        return local.grabber.grab()

    tracker = Tracker(store, grab, cfg, log=log)
    holder = {}

    def on_command(name):
        """Команды от повторного запуска: show — показать окно."""
        if name == "show" and holder.get("app"):
            holder["app"].show_main()

    server = open_server(cfg, tracker, on_command, hidden)

    log("MMReon запущен. " + tracker.summary())
    for note in (gsi_install.auto_install(cfg), gsi_install.ensure_current(cfg)):
        if note:
            log(note)
    log(f"Жду данные от Доты на 127.0.0.1:{cfg['gsi_port']}.")
    scanner = threading.Thread(target=tracker.run_scanner, daemon=True, name="scanner")
    scanner.start()

    app = None
    try:
        if no_ui:
            log("Ctrl+C — выход.")
            scanner.join()
        else:
            from mmreon.app import App
            app = App(tracker, cfg)
            holder["app"] = app
            app.run(start_hidden=hidden)
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        fail(f"MMReon остановился с ошибкой: {exc!r}")
    finally:
        tracker.stop()
        server.shutdown()
        server.server_close()
        log("Остановлено. " + tracker.summary())
        if app is not None and app.restart_requested:
            from mmreon import updater
            log("Перезапуск после обновления")
            updater.spawn_restart(app.restart_requested if isinstance(app.restart_requested, dict) else None)


if __name__ == "__main__":
    main()
