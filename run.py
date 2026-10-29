"""MMReon — запуск трекера.

    python run.py            — с окном и виджетом
    python run.py --no-ui    — только консоль
"""
import sys
import threading

from mmreon import config, ocr
from mmreon.gsi import start_server
from mmreon.screen import Grabber
from mmreon.store import Store
from mmreon.tracker import Tracker


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

    tracker = Tracker(store, grab, cfg)
    try:
        server = start_server(cfg["gsi_port"], cfg["gsi_token"], tracker.on_gsi)
    except OSError as exc:
        sys.exit(f"Не удалось открыть порт {cfg['gsi_port']}: {exc}. Возможно, трекер уже запущен.")

    print("MMReon запущен.", tracker.summary())
    print(f"Жду данные от Доты на 127.0.0.1:{cfg['gsi_port']}.")
    scanner = threading.Thread(target=tracker.run_scanner, daemon=True, name="scanner")
    scanner.start()

    try:
        if no_ui:
            print("Ctrl+C — выход.")
            scanner.join()
        else:
            from mmreon.app import App
            print("Окно можно закрыть — трекер продолжит работать. Выход: кнопка «Выйти» или Ctrl+C здесь.")
            App(tracker, cfg).run()
    except KeyboardInterrupt:
        pass
    finally:
        tracker.stop()
        server.shutdown()
        print("Остановлено.", tracker.summary())


if __name__ == "__main__":
    main()
