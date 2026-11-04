"""Per-user Luwag installer. A setup window copies the app and adds shortcuts. No administrator prompt."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def payload() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    bundled = base / "payload" / "Luwag-windows.zip"
    if bundled.exists():
        return bundled
    return Path(__file__).resolve().parent / "Luwag-windows.zip"


def page() -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
    bundled = base / "packaging" / "setup.html"
    if bundled.exists():
        return bundled
    return Path(__file__).resolve().parent / "setup.html"


def dest_dir() -> Path:
    return Path(os.environ["LOCALAPPDATA"]) / "Luwag" / "app"


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


class SetupApi:
    def __init__(self):
        self._window = None
        self._exe = None

    def info(self):
        package = payload()
        return {
            "dest": str(dest_dir()),
            "ready": package.exists(),
            "error": "" if package.exists() else "The Luwag package is missing from this installer.",
        }

    def install(self):
        package = payload()
        if not package.exists():
            return {"ok": False, "error": "The Luwag package is missing from this installer."}
        dest = dest_dir()
        try:
            if dest.exists():
                shutil.rmtree(dest)
            dest.mkdir(parents=True)
            with zipfile.ZipFile(package) as archive:
                archive.extractall(dest)
            exe = dest / "Luwag.exe"
            if not exe.exists():
                return {"ok": False, "error": "Luwag.exe was not in the package."}
            shortcuts(exe, dest)
        except OSError as exc:
            return {"ok": False, "error": "Close Luwag if it is open, then try again. " + str(exc)}
        self._exe = exe
        return {"ok": True, "dest": str(dest)}

    def open_app(self):
        exe = self._exe or (dest_dir() / "Luwag.exe")
        if exe.exists():
            subprocess.Popen([str(exe)])
        if self._window is not None:
            self._window.destroy()
        return {"ok": True}

    def close(self):
        if self._window is not None:
            self._window.destroy()
        return {"ok": True}


def main() -> None:
    import webview

    api = SetupApi()
    window = webview.create_window(
        "Luwag Setup",
        str(page()),
        js_api=api,
        width=460,
        height=640,
        resizable=False,
        frameless=True,
        easy_drag=False,
        background_color="#F7F6F4",
    )
    api._window = window
    webview.start(gui="edgechromium")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, f"Luwag Setup stopped.\n{exc}", "Luwag Setup", 0x10)
        sys.exit(1)
