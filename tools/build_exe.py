"""Собирает MMReon в папку с программой MMReon.exe — Python для запуска не нужен.

    pip install pyinstaller
    python tools/build_exe.py

Результат: dist/MMReon/ — эту папку можно скопировать куда угодно или заархивировать
и отдать другу. Tesseract копируется внутрь (папка tesseract рядом с MMReon.exe),
поэтому отдельно его ставить не нужно. Данные (журнал, настройки) создаются в папке data
рядом с MMReon.exe.
"""
import os
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
# Консоль Windows может быть не в UTF-8: не падаем на русских сообщениях.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def find_tesseract() -> Path | None:
    from mmreon import config
    cfg = config.load()
    candidates = [cfg.get("tesseract_cmd"), r"C:\Program Files\Tesseract-OCR\tesseract.exe"]
    for c in candidates:
        if c and Path(c).exists():
            return Path(c).parent
    found = shutil.which("tesseract")
    return Path(found).parent if found else None


def main():
    try:
        import PyInstaller.__main__ as pyi
    except ImportError:
        sys.exit("Нужен PyInstaller: pip install pyinstaller")

    sep = ";" if sys.platform == "win32" else ":"
    pkg = ROOT / "mmreon"
    args = [
        str(ROOT / "MMReon.pyw"),
        "--name", "MMReon",
        "--icon", str(pkg / "assets" / "mmreon.ico"),
        "--windowed", "--onedir", "--noconfirm", "--clean",
        "--distpath", str(ROOT / "dist"),
        "--workpath", str(ROOT / "build"),
        "--specpath", str(ROOT / "build"),
        "--add-data", f"{pkg / 'ui'}{sep}mmreon/ui",
        "--add-data", f"{pkg / 'assets'}{sep}mmreon/assets",
        "--hidden-import", "pystray._win32",
        "--collect-submodules", "webview",
        "--collect-data", "certifi",          # сертификаты HTTPS для проверки обновлений
        "--paths", str(ROOT),
    ]
    print("Сборка… это займёт пару минут.")
    pyi.run(args)

    out = ROOT / "dist" / "MMReon"
    tess = find_tesseract()
    if tess:
        target = out / "tesseract"
        if target.exists():
            shutil.rmtree(target)
        # Только сам движок и английские данные: обучающие утилиты и другие языки не нужны.
        shutil.copytree(tess, target, ignore=shutil.ignore_patterns(
            "*training*.exe", "lstm*.exe", "text2image.exe", "*.html", "unicharset*.exe", "wordlist2dawg.exe",
            "ambiguous_words.exe", "classifier_tester.exe", "cntraining.exe", "combine_*.exe", "dawg2wordlist.exe",
            "merge_unicharsets.exe", "mftraining.exe", "set_unicharset_properties.exe", "shapeclustering.exe",
            "tesseract-uninstall.exe", "tessdata", "doc"))
        tessdata = target / "tessdata"
        tessdata.mkdir(exist_ok=True)
        for name in ("eng.traineddata", "osd.traineddata"):
            if (tess / "tessdata" / name).exists():
                shutil.copy2(tess / "tessdata" / name, tessdata / name)
        if (tess / "tessdata" / "configs").exists():
            shutil.copytree(tess / "tessdata" / "configs", tessdata / "configs")
        print(f"Tesseract скопирован из {tess}")
    else:
        print("Tesseract не найден — положите его вручную в dist/MMReon/tesseract/")
        if os.environ.get("CI"):
            sys.exit(1)
    (out / "THIRD_PARTY_NOTICES.txt").write_text(NOTICES, encoding="utf-8")
    print(f"Готово: {out / 'MMReon.exe'}")


NOTICES = """MMReon использует сторонние программы и библиотеки:

- Tesseract OCR (папка tesseract) — Apache License 2.0, https://github.com/tesseract-ocr/tesseract
  Сборка для Windows: UB Mannheim, https://github.com/UB-Mannheim/tesseract
- pywebview — BSD-3-Clause, https://github.com/r0x0r/pywebview
- OpenCV — Apache License 2.0, https://opencv.org
- pystray — LGPL-3.0, https://github.com/moses-palmer/pystray
- Pillow — HPND, https://python-pillow.org
- mss — MIT, https://github.com/BoboTiG/python-mss
- pytesseract — Apache License 2.0, https://github.com/madmaze/pytesseract
- Python — PSF License, https://www.python.org

Dota 2 — товарный знак Valve Corporation. MMReon не связан с Valve.
Иконки медалей загружаются с OpenDota, иконки героев и предметов — с серверов Steam.
"""


if __name__ == "__main__":
    main()
