"""Luwag window. The frame is drawn by the page, the same way LodiSave Gallery does it."""

from __future__ import annotations

import ctypes
import os
import sys
import traceback

import webview

from engine import Engine

HERE = os.path.dirname(os.path.abspath(__file__))
WMSZ = {
    "left": 1,
    "right": 2,
    "top": 3,
    "topleft": 4,
    "topright": 5,
    "bottom": 6,
    "bottomleft": 7,
    "bottomright": 8,
}


class Api:
    def __init__(self):
        self._engine = Engine()
        self._window = None

    def ready(self):
        return self._engine.snapshot()

    def poll(self):
        return self._engine.snapshot()

    def scan(self, mode):
        return self._engine.start(mode)

    def cancel(self):
        return self._engine.cancel()

    def prepare(self, ids):
        return self._engine.prepare(list(ids or []))

    def recycle(self, ids, word):
        return self._engine.recycle(list(ids or []), word or "")

    def empty_bin(self, word):
        return self._engine.empty_bin(word or "")

    def protect(self, path):
        return self._engine.protect_path(path or "")

    def unprotect(self, path):
        return self._engine.unprotect_path(path or "")

    def save_settings(self, patch):
        return self._engine.update_settings(patch or {})

    def reveal(self, path):
        return self._engine.reveal(path or "")

    def open_bin(self):
        return self._engine.open_bin()

    def open_storage(self):
        return self._engine.open_storage_settings()

    def copy_text(self, text):
        return self._engine.copy_text(text or "")

    def summary(self):
        return {"ok": True, "text": self._engine.summary()}

    def export_csv(self):
        return self._engine.export_csv()

    def confirm_dupe(self, group_id):
        return self._engine.confirm_dupe(group_id or "")

    def minimize(self):
        self._window.minimize()
        return {"ok": True}

    def toggle_maximize(self):
        if self._maximized():
            self._window.restore()
            return {"maximized": False}
        self._window.maximize()
        return {"maximized": True}

    def close(self):
        self._window.destroy()
        return {"ok": True}

    def window_state(self):
        return {"maximized": self._maximized()}

    def start_resize(self, edge):
        direction = WMSZ.get(edge or "")
        if not direction or self._maximized():
            return {"ok": False}
        hwnd = int(self._window.native.Handle.ToInt64())
        user32 = ctypes.windll.user32
        user32.ReleaseCapture()
        # SC_SIZE lets Windows run the resize, including the corner grips.
        user32.SendMessageW(hwnd, 0x0112, 0xF000 + direction, 0)
        return {"ok": True}

    def _maximized(self):
        try:
            return int(self._window.native.WindowState) == 2
        except Exception:
            return False


def main():
    api = Api()
    phone = "--phone" in sys.argv
    page = os.path.join(HERE, "ui", "index.html")
    if phone:
        page += "?shell=phone"
    window = webview.create_window(
        "Luwag Phone" if phone else "Luwag Storage",
        page,
        js_api=api,
        width=420 if phone else 1280,
        height=844 if phone else 820,
        min_size=(360, 640) if phone else (1024, 680),
        frameless=True,
        easy_drag=False,
        background_color="#F7F6F4",
        text_select=True,
    )
    api._window = window

    def apply_icon():
        try:
            import clr
            clr.AddReference("System.Drawing")
            from System.Drawing import Icon
            window.native.Icon = Icon(os.path.join(HERE, "ui", "models", "logo.ico"))
        except Exception:
            return

    webview.start(apply_icon, gui="edgechromium")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log_dir = os.path.join(os.environ.get("LOCALAPPDATA") or HERE, "Luwag")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "error.log")
        with open(log_path, "a", encoding="utf-8") as handle:
            traceback.print_exc(file=handle)
        ctypes.windll.user32.MessageBoxW(None, f"Luwag stopped. Details are in {log_path}", "Luwag", 0x10)
        sys.exit(1)
