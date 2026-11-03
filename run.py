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
from mmreon.gsi import start_server
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


def main():
    no_ui = "--no-ui" in sys.argv
    cfg = config.load()
    ocr.set_tesseract(cfg["tesseract_cmd"])
    store = Store(config.MATCHES_PATH)

    local = threading.local()

    def grab():
        if not hasattr(local, "grabber"):
            local.grabber = Grabber()
        return local.grabber.grab()

    tracker = Tracker(store, grab, cfg, log=log)
    server = None
    for attempt in range(6):    # после обновления старая копия может ещё закрываться
        try:
            server = start_server(cfg["gsi_port"], cfg["gsi_token"], tracker.on_gsi)
            break
        except OSError:
            time.sleep(1)
    if server is None:
        fail("MMReon уже запущен (или порт занят другой программой).")

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
            app.run(start_hidden="--tray" in sys.argv)
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
