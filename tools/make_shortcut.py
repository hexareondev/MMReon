"""Создаёт ярлык MMReon с иконкой.

    python tools/make_shortcut.py             — на рабочем столе
    python tools/make_shortcut.py --startup   — ещё и в автозагрузке (запуск вместе с Windows)
"""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PS = r"""
$shell = New-Object -ComObject WScript.Shell
foreach ($folder in $env:MMR_FOLDERS.Split('|')) {
  $dir = [Environment]::GetFolderPath($folder)
  $s = $shell.CreateShortcut((Join-Path $dir 'MMReon.lnk'))
  $s.TargetPath = $env:MMR_TARGET
  $s.Arguments = '"' + $env:MMR_SCRIPT + '"'
  $s.WorkingDirectory = $env:MMR_ROOT
  $s.IconLocation = $env:MMR_ICON
  $s.Description = 'MMReon — трекер рейтинга Dota 2'
  $s.Save()
  Write-Output (Join-Path $dir 'MMReon.lnk')
}
"""


def main():
    if os.name != "nt":
        sys.exit("Ярлыки создаются только в Windows.")
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    if not pythonw.exists():
        sys.exit(f"Не найден {pythonw}")
    folders = ["Desktop"] + (["Startup"] if "--startup" in sys.argv else [])
    env = dict(os.environ,
               MMR_FOLDERS="|".join(folders),
               MMR_TARGET=str(pythonw),
               MMR_SCRIPT=str(ROOT / "MMReon.pyw"),
               MMR_ROOT=str(ROOT),
               MMR_ICON=str(ROOT / "mmreon" / "assets" / "mmreon.ico"))
    result = subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", PS],
                            env=env, capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit("Не удалось создать ярлык:\n" + result.stderr)
    for line in result.stdout.splitlines():
        if line.strip():
            print("Ярлык создан:", line.strip())


if __name__ == "__main__":
    main()
