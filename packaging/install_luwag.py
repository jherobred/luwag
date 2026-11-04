"""Per-user Luwag installer. Copies the bundled app and adds shortcuts. No administrator prompt."""

from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def payload() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    bundled = base / "payload" / "Luwag-windows.zip"
    if bundled.exists():
        return bundled
    return base / "Luwag-windows.zip"


def shortcuts(exe: Path, dest: Path) -> None:
    script = Path(os.environ["TEMP"]) / "luwag-shortcut.ps1"
    start = Path(os.environ["APPDATA"]) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Luwag Storage.lnk"
    desktop = Path(os.environ["USERPROFILE"]) / "Desktop" / "Luwag Storage.lnk"
    text = "\n".join([
        "$w = New-Object -ComObject WScript.Shell",
        f"$targets = @('{start}', '{desktop}')",
        "foreach ($p in $targets) {",
        "  $s = $w.CreateShortcut($p)",
        f"  $s.TargetPath = '{exe}'",
        f"  $s.WorkingDirectory = '{dest}'",
        f"  $s.IconLocation = '{exe},0'",
        "  $s.Description = 'Luwag Storage'",
        "  $s.Save()",
        "}",
    ])
    script.write_text(text, encoding="utf-8")
    subprocess.check_call(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)])
    script.unlink(missing_ok=True)


def main() -> None:
    package = payload()
    if not package.exists():
        ctypes.windll.user32.MessageBoxW(None, "The Luwag package is missing from this installer.", "Luwag Setup", 0x10)
        sys.exit(1)
    dest = Path(os.environ["LOCALAPPDATA"]) / "Luwag" / "app"
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    with zipfile.ZipFile(package) as archive:
        archive.extractall(dest)
    exe = dest / "Luwag.exe"
    if not exe.exists():
        ctypes.windll.user32.MessageBoxW(None, "Luwag.exe was not in the package.", "Luwag Setup", 0x10)
        sys.exit(1)
    shortcuts(exe, dest)
    ctypes.windll.user32.MessageBoxW(None, "Luwag Storage is installed for this user.", "Luwag Setup", 0x40)
    subprocess.Popen([str(exe)])


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        ctypes.windll.user32.MessageBoxW(None, f"Luwag Setup stopped.\n{exc}", "Luwag Setup", 0x10)
        sys.exit(1)
