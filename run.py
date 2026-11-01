"""MMReon — запуск трекера.

    MMReon.pyw               — двойной клик: окно и виджет без консоли
    python run.py            — то же, но с консолью (удобно для отладки)
    python run.py --no-ui    — только консоль
"""
import ctypes
import os
import sys
import threading
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
    try:
        server = start_server(cfg["gsi_port"], cfg["gsi_token"], tracker.on_gsi)
    except OSError:
        fail("MMReon уже запущен (или порт занят другой программой).")

    log("MMReon запущен. " + tracker.summary())
    note = gsi_install.ensure_current(cfg)
    if note:
        log(note)
    log(f"Жду данные от Доты на 127.0.0.1:{cfg['gsi_port']}.")
    scanner = threading.Thread(target=tracker.run_scanner, daemon=True, name="scanner")
    scanner.start()

    try:
        if no_ui:
            log("Ctrl+C — выход.")
            scanner.join()
        else:
            from mmreon.app import App
            App(tracker, cfg).run()
    except KeyboardInterrupt:
        pass
    except Exception as exc:
        fail(f"MMReon остановился с ошибкой: {exc!r}")
    finally:
        tracker.stop()
        server.shutdown()
        log("Остановлено. " + tracker.summary())


if __name__ == "__main__":
    main()
