"""Собирает MMReon в папку с программой MMReon.exe — Python для запуска не нужен.

    pip install pyinstaller
    python tools/build_exe.py

Результат: dist/MMReon/ — эту папку можно скопировать куда угодно или заархивировать
и отдать другу. Tesseract копируется внутрь (папка tesseract рядом с MMReon.exe),
поэтому отдельно его ставить не нужно. Данные (журнал, настройки) создаются в папке data
рядом с MMReon.exe.
"""
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


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
        # Только сам движок и английские данные: обучающие утилиты не нужны.
        shutil.copytree(tess, target, ignore=shutil.ignore_patterns(
            "*training*.exe", "lstm*.exe", "text2image.exe", "*.html", "unicharset*.exe", "wordlist2dawg.exe",
            "ambiguous_words.exe", "classifier_tester.exe", "cntraining.exe", "combine_*.exe", "dawg2wordlist.exe",
            "merge_unicharsets.exe", "mftraining.exe", "set_unicharset_properties.exe", "shapeclustering.exe",
            "tesseract-uninstall.exe"))
        print(f"Tesseract скопирован из {tess}")
    else:
        print("Tesseract не найден — положите его вручную в dist/MMReon/tesseract/")
    print(f"Готово: {out / 'MMReon.exe'}")


if __name__ == "__main__":
    main()
