"""MMReon — запуск трекера.

    python run.py

Оставьте окно консоли открытым, пока играете.
"""
import sys
import threading

from mmreon import config, ocr
from mmreon.gsi import start_server
from mmreon.screen import Grabber
from mmreon.store import Store
from mmreon.tracker import Tracker


def main():
    cfg = config.load()
    ocr.set_tesseract(cfg["tesseract_cmd"])
    store = Store(config.MATCHES_PATH)

    local = threading.local()

    def grab():
        if not hasattr(local, "grabber"):
            local.grabber = Grabber()
        return local.grabber.grab()

    tracker = Tracker(store, grab, cfg)
    try:
        server = start_server(cfg["gsi_port"], cfg["gsi_token"], tracker.on_gsi)
    except OSError as exc:
        sys.exit(f"Не удалось открыть порт {cfg['gsi_port']}: {exc}. Возможно, трекер уже запущен.")

    print("MMReon запущен.", tracker.summary())
    print(f"Жду данные от Доты на 127.0.0.1:{cfg['gsi_port']}. Ctrl+C — выход.")
    try:
        tracker.run_scanner()
    except KeyboardInterrupt:
        pass
    finally:
        tracker.stop()
        server.shutdown()
        print("Остановлено.", tracker.summary())


if __name__ == "__main__":
    main()
