"""Проверка распознавания на скриншоте или на живом окне Доты.

    python tools/test_ocr.py screenshot.png   — прочитать сохранённый скриншот
    python tools/test_ocr.py --live           — через 5 секунд снять окно Доты
                                                (успейте переключиться на «Профиль → История»)
"""
import sys
import time
from pathlib import Path

import cv2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from mmreon import config, ocr  # noqa: E402


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    cfg = config.load()
    ocr.set_tesseract(cfg["tesseract_cmd"])

    if sys.argv[1] == "--live":
        from mmreon.screen import Grabber
        print("Переключитесь на Доту, вкладка «Профиль → История». Снимок через 5 секунд...")
        time.sleep(5)
        frame = Grabber().grab()
        if frame is None:
            sys.exit("Окно Dota 2 не найдено или не было активным.")
        config.DEBUG_DIR.mkdir(parents=True, exist_ok=True)
        path = config.DEBUG_DIR / f"live_{int(time.time())}.png"
        cv2.imwrite(str(path), frame)
        print(f"Кадр сохранён: {path}")
    else:
        frame = cv2.imread(sys.argv[1])
        if frame is None:
            sys.exit(f"Не удалось открыть {sys.argv[1]}")

    print(f"Размер кадра: {frame.shape[1]}×{frame.shape[0]}")
    result = ocr.read(frame)
    if not result:
        print("Вкладка «История» не найдена или цифра не прочиталась.")
    else:
        print(f"Рейтинг: {result['rating']}")
        print(f"Уверенность в ранге: {result['confidence']}%")
        print(f"Совпадение подписи: {result['anchor_score']}")


if __name__ == "__main__":
    main()
