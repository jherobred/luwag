"""Measure this PC and send chosen files to the Recycle Bin.

Protected paths are refused here, not only in the window. A scan never deletes.
"""

from __future__ import annotations

import csv
import ctypes
import json
import os
import shutil
import subprocess
import threading
import time
from collections import defaultdict
from ctypes import wintypes

CREATE_NO_WINDOW = 0x08000000
REPARSE = 0x400
TWO_GB = 2 * 1024 ** 3
FILE_CAP = 5000
LIST_CAP = 800
LARGE_CAP = 300
BUNDLE_CAP = 60
DUPE_CAP = 150
HASH_GROUP_MAX = 12
MIN_DUPE = 1024 * 1024

DENY_PARTS = {".ssh", ".gnupg", ".aws", ".kube", ".azure", "credentials"}
DENY_FILES = {"ntuser.dat", "ntuser.dat.log1", "ntuser.dat.log2", "ntuser.ini", "auth.json"}
BROWSER_FILES = {
    "login data", "login data-journal", "cookies", "cookies-journal",
    "web data", "web data-journal", "history", "history-journal",
    "bookmarks", "preferences", "local state",
}
QUIET_DIRS = {"$recycle.bin", "system volume information", "recovery", "config.msi"}
SKIP_WALK = {".git", ".svn", ".hg"}

DEFAULTS = {
    "theme": "system",
    "motion": None,
    "largeMinMB": 100,
    "downloadDays": 30,
    "tempDays": 7,
    "extraProtected": [],
    "history": [],
}


def fmt_bytes(n):
    n = int(n or 0)
    sign = "-" if n < 0 else ""
    n = abs(n)
    units = ("B", "KB", "MB", "GB", "TB")
    value = float(n)
    idx = 0
    while value >= 1024 and idx < len(units) - 1:
        value /= 1024
        idx += 1
    if idx == 0 or value >= 100:
        text = f"{value:.0f}"
    elif value >= 10:
        text = f"{value:.1f}"
    else:
        text = f"{value:.2f}"
    return sign + text + " " + units[idx]


def norm(path):
    return os.path.normcase(os.path.abspath(path))


def under(path, root):
    """True when path is root or a child of root. C:\\Windows does not cover C:\\Windows.old."""
    try:
        path_n = norm(path)
        root_n = norm(root)
        return os.path.commonpath([path_n, root_n]) == root_n
    except (ValueError, OSError):
        return False


def is_reparse(st):
    return bool(getattr(st, "st_file_attributes", 0) & REPARSE)


def known_folder(guid_bytes):
    class GUID(ctypes.Structure):
        _fields_ = [
            ("Data1", ctypes.c_ulong),
            ("Data2", ctypes.c_ushort),
            ("Data3", ctypes.c_ushort),
            ("Data4", ctypes.c_ubyte * 8),
        ]

    data1, data2, data3, data4 = guid_bytes
    fid = GUID(data1, data2, data3, (ctypes.c_ubyte * 8)(*data4))
    ptr = ctypes.c_void_p()
    hr = ctypes.windll.shell32.SHGetKnownFolderPath(ctypes.byref(fid), 0, None, ctypes.byref(ptr))
    if hr != 0 or not ptr.value:
        return ""
    try:
        return ctypes.wstring_at(ptr.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(ptr)


FOLDERS = {
    "desktop": (0xB4BFCC3A, 0xDB2C, 0x424C, (0xB0, 0x29, 0x7F, 0xE9, 0x9A, 0x87, 0xC6, 0x41)),
    "documents": (0xFDD39AD0, 0x238F, 0x46AF, (0xAD, 0xB4, 0x6C, 0x85, 0x48, 0x03, 0x69, 0xC7)),
    "downloads": (0x374DE290, 0x123F, 0x4565, (0x91, 0x64, 0x39, 0xC4, 0x92, 0x5E, 0x46, 0x7B)),
    "music": (0x4BD8D571, 0x6D19, 0x48D3, (0xBE, 0x97, 0x42, 0x22, 0x20, 0x08, 0x0E, 0x43)),
    "pictures": (0x33E28130, 0x4E1E, 0x4676, (0x83, 0x5A, 0x98, 0x39, 0x5C, 0x3B, 0xC3, 0xBB)),
    "videos": (0x18989B1D, 0x99B5, 0x455B, (0x84, 0x1C, 0xAB, 0x7C, 0x74, 0xE4, 0xDD, 0xFC)),
}


def folder(name, fallback):
    found = known_folder(FOLDERS[name])
    if found and os.path.isdir(found):
        return found
    path = os.path.join(os.path.expanduser("~"), fallback)
    return path if os.path.isdir(path) else ""


def hard_roots():
    roots = []
    for key in ("WINDIR", "SystemRoot", "ProgramFiles", "ProgramFiles(x86)", "ProgramData"):
        value = os.environ.get(key)
        if value and os.path.isdir(value):
            roots.append(os.path.abspath(value))
    seen = set()
    out = []
    for root in roots:
        key = norm(root)
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def list_drives():
    out = []
    mask = ctypes.windll.kernel32.GetLogicalDrives()
    for index in range(26):
        if not (mask & (1 << index)):
            continue
        letter = chr(65 + index)
        path = f"{letter}:\\"
        kind = ctypes.windll.kernel32.GetDriveTypeW(path)
        if kind not in (2, 3):
            continue
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        out.append({
            "letter": letter,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "kind": "fixed" if kind == 3 else "removable",
        })
    return out


def query_recycle():
    class SHQUERYRBINFO(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.DWORD),
            ("i64Size", ctypes.c_longlong),
            ("i64NumItems", ctypes.c_longlong),
        ]

    info = SHQUERYRBINFO()
    info.cbSize = ctypes.sizeof(SHQUERYRBINFO)
    shell32 = ctypes.windll.shell32
    shell32.SHQueryRecycleBinW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(SHQUERYRBINFO)]
    shell32.SHQueryRecycleBinW.restype = ctypes.HRESULT
    hr = shell32.SHQueryRecycleBinW(None, ctypes.byref(info))
    if hr != 0:
        return {"bytes": 0, "count": 0, "error": f"Windows did not share the Recycle Bin ({hr:#x})."}
    return {"bytes": int(info.i64Size), "count": int(info.i64NumItems), "error": ""}


def storage_sense():
    import winreg
    path = r"Software\Microsoft\Windows\CurrentVersion\StorageSense\Parameters\StoragePolicy"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, path) as key:
            value, _typ = winreg.QueryValueEx(key, "01")
            return bool(int(value))
    except OSError:
        return None


def physical_disks():
    command = (
        "Get-PhysicalDisk | Select-Object FriendlyName, HealthStatus, Size | ConvertTo-Json -Compress"
    )
    try:
        done = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", command],
            capture_output=True, text=True, timeout=15, creationflags=CREATE_NO_WINDOW,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {"error": f"Disk health did not answer ({exc.__class__.__name__})."}
    if done.returncode != 0:
        detail = (done.stderr or "Windows did not return disk health.").strip().splitlines()
        return {"error": detail[0][:240] if detail else "Windows did not return disk health."}
    raw = (done.stdout or "").strip()
    if not raw:
        return {"error": "Windows returned no disk health."}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {"error": "Windows returned disk health in an unexpected form."}
    if isinstance(data, dict):
        data = [data]
    disks = []
    for row in data:
        if not isinstance(row, dict):
            continue
        try:
            size = int(row.get("Size") or 0)
        except (TypeError, ValueError):
            size = 0
        disks.append({
            "name": str(row.get("FriendlyName") or "Disk"),
            "status": str(row.get("HealthStatus") or "Unknown"),
            "size": size,
        })
    if not disks:
        return {"error": "Windows returned no disks."}
    return {"disks": disks}


def slug(text):
    keep = []
    for ch in text.lower():
        keep.append(ch if ch.isalnum() else "-")
    return "".join(keep).strip("-")[:48] or "item"


class Engine:
    def __init__(self, data_dir=None):
        self.data_dir = data_dir or os.path.join(os.environ.get("LOCALAPPDATA") or os.path.expanduser("~"), "Luwag")
        os.makedirs(self.data_dir, exist_ok=True)
        self.settings_path = os.path.join(self.data_dir, "settings.json")
        self.settings = self._load_settings()
        self.lock = threading.Lock()
        self.cancelled = False
        self.thread = None
        self.seq = 0
        self.catalog = {}
        self.allowed_roots = set()
        self.allowed_files = set()
        self.targets = []
        self.files = []
        self.bundles = []
        self.dupes = []
        self.drives = []
        self.health = {"disks": [], "error": ""}
        self.sense = None
        self.recycle_info = {"bytes": 0, "count": 0, "error": ""}
        self.errors = []
        self.truncated = {}
        self.hard = hard_roots()
        self.guarded = self._guarded()
        self.state = {
            "rev": 0,
            "running": False,
            "phase": "idle",
            "message": "Not scanned yet.",
            "current": "",
            "partial": False,
            "scannedAt": None,
        }
        self.last_bump = 0.0

    def _guarded(self):
        found = []
        for name, fallback in (
            ("desktop", "Desktop"),
            ("documents", "Documents"),
            ("pictures", "Pictures"),
            ("videos", "Videos"),
            ("music", "Music"),
        ):
            path = folder(name, fallback)
            if path:
                found.append(path)
        one = os.path.join(os.path.expanduser("~"), "OneDrive")
        if os.path.isdir(one):
            found.append(one)
        return found

    def _load_settings(self):
        data = dict(DEFAULTS)
        try:
            with open(self.settings_path, encoding="utf-8") as handle:
                saved = json.load(handle)
            if isinstance(saved, dict):
                data.update({k: saved[k] for k in DEFAULTS if k in saved})
        except (OSError, json.JSONDecodeError):
            pass
        data["extraProtected"] = [p for p in data.get("extraProtected") or [] if isinstance(p, str)]
        data["history"] = [h for h in data.get("history") or [] if isinstance(h, dict)][-90:]
        data["theme"] = data["theme"] if data["theme"] in ("system", "light", "dark") else "system"
        if data["motion"] not in (True, False, None):
            data["motion"] = None
        data["largeMinMB"] = min(10000, max(10, int(data["largeMinMB"] or 100)))
        data["downloadDays"] = min(3650, max(1, int(data["downloadDays"] or 30)))
        data["tempDays"] = min(3650, max(1, int(data["tempDays"] or 7)))
        return data

    def _save_settings(self):
        tmp = self.settings_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(self.settings, handle, indent=2)
        os.replace(tmp, self.settings_path)

    def is_rootish(self, path):
        drive, rest = os.path.splitdrive(os.path.abspath(path))
        if rest in ("\\", "/"):
            return True
        home = norm(os.path.expanduser("~"))
        path_n = norm(path)
        if path_n == home:
            return True
        users = norm(os.path.dirname(os.path.expanduser("~")))
        return path_n == users

    def is_protected(self, path):
        if not path:
            return True
        try:
            full = os.path.abspath(path)
        except OSError:
            return True
        if self.is_rootish(full):
            return True
        for root in self.hard:
            if under(full, root):
                return True
        if under(full, self.data_dir):
            return True
        parts = [part.casefold() for part in full.split(os.sep) if part]
        if any(part in DENY_PARTS for part in parts):
            return True
        name = parts[-1] if parts else ""
        if name in DENY_FILES or name in BROWSER_FILES:
            return True
        for extra in self.settings["extraProtected"]:
            if extra and under(full, extra):
                return True
        return False

    def is_guarded(self, path):
        return any(under(path, root) for root in self.guarded)

    def _next_id(self, prefix):
        self.seq += 1
        return f"{prefix}{self.seq}"

    def _bump(self, force=False):
        now = time.monotonic()
        if force or now - self.last_bump >= 0.25:
            self.state["rev"] += 1
            self.last_bump = now

    def note(self, path, message=None):
        now = time.monotonic()
        if message is None and now - self.last_bump < 0.25:
            return
        with self.lock:
            self.state["current"] = path or ""
            if message:
                self.state["message"] = message
            self._bump(bool(message))

    def add_error(self, path, message):
        name = os.path.basename(path).casefold()
        if name in QUIET_DIRS:
            return
        with self.lock:
            if len(self.errors) >= 40:
                self.truncated["errors"] = True
                return
            self.errors.append({"path": path, "message": str(message)[:240]})
            self._bump()

    def snapshot(self):
        with self.lock:
            settings = {
                "theme": self.settings["theme"],
                "motion": self.settings["motion"],
                "largeMinMB": self.settings["largeMinMB"],
                "downloadDays": self.settings["downloadDays"],
                "tempDays": self.settings["tempDays"],
                "extraProtected": list(self.settings["extraProtected"]),
            }
            payload = {
                "rev": self.state["rev"],
                "running": self.state["running"],
                "phase": self.state["phase"],
                "message": self.state["message"],
                "current": self.state["current"],
                "partial": self.state["partial"],
                "scannedAt": self.state["scannedAt"],
                "drives": list(self.drives),
                "health": self.health,
                "storageSense": self.sense,
                "recycle": dict(self.recycle_info),
                "targets": list(self.targets),
                "files": list(self.files),
                "bundles": list(self.bundles),
                "dupes": list(self.dupes),
                "errors": list(self.errors),
                "truncated": dict(self.truncated),
                "protected": self._protected_rows(),
                "history": list(self.settings["history"]),
                "settings": settings,
            }
        return json.loads(json.dumps(payload))

    def _protected_rows(self):
        rows = []
        for path in self.hard:
            rows.append({"path": path, "why": "Windows system folder. Luwag never changes it.", "removable": False})
        for path in self.guarded:
            rows.append({
                "path": path,
                "why": "Personal folder. A file here can be recycled only after you type RECYCLE.",
                "removable": False,
            })
        rows.append({
            "path": "Git history (.git)",
            "why": "Skipped in every scan. Removing it would delete a project's history.",
            "removable": False,
        })
        rows.append({
            "path": "Sign-in files, keys, and browser passwords",
            "why": "Login Data, Cookies, History, .ssh, .aws, and auth.json are refused.",
            "removable": False,
        })
        rows.append({
            "path": self.data_dir,
            "why": "Luwag keeps its own settings here.",
            "removable": False,
        })
        for path in self.settings["extraProtected"]:
            rows.append({"path": path, "why": "You protected this.", "removable": True})
        return rows

    def update_settings(self, patch):
        if not isinstance(patch, dict):
            return {"ok": False, "error": "Settings were not a form."}
        with self.lock:
            if "theme" in patch and patch["theme"] in ("system", "light", "dark"):
                self.settings["theme"] = patch["theme"]
            if "motion" in patch and patch["motion"] in (True, False, None):
                self.settings["motion"] = patch["motion"]
            if "largeMinMB" in patch:
                self.settings["largeMinMB"] = min(10000, max(10, int(patch["largeMinMB"])))
            if "downloadDays" in patch:
                self.settings["downloadDays"] = min(3650, max(1, int(patch["downloadDays"])))
            if "tempDays" in patch:
                self.settings["tempDays"] = min(3650, max(1, int(patch["tempDays"])))
            self._save_settings()
            self._bump(True)
        return {"ok": True, "settings": self.snapshot()["settings"]}

    def protect_path(self, path):
        full = os.path.abspath(path)
        if self.is_rootish(full) or any(under(full, root) and norm(full) == norm(root) for root in self.hard):
            return {"ok": False, "error": "That folder is already protected, or it is a whole drive."}
        if not os.path.exists(full):
            return {"ok": False, "error": "That path is not on this PC."}
        with self.lock:
            if not any(norm(p) == norm(full) for p in self.settings["extraProtected"]):
                self.settings["extraProtected"].append(full)
                self._save_settings()
            self._bump(True)
        return {"ok": True}

    def unprotect_path(self, path):
        with self.lock:
            self.settings["extraProtected"] = [p for p in self.settings["extraProtected"] if norm(p) != norm(path)]
            self._save_settings()
            self._bump(True)
        return {"ok": True}

    def start(self, mode):
        if mode not in ("quick", "disk"):
            return {"ok": False, "error": "Unknown scan."}
        with self.lock:
            if self.state["running"]:
                return {"ok": False, "error": "A scan is already running."}
            self.cancelled = False
            self.state["running"] = True
            self.state["phase"] = mode
            self.state["partial"] = False
            self.state["message"] = "Starting the scan."
            self.state["current"] = ""
            self._bump(True)
        target = self._quick if mode == "quick" else self._disk
        self.thread = threading.Thread(target=self._guard, args=(target, mode), daemon=True)
        self.thread.start()
        return {"ok": True}

    def cancel(self):
        self.cancelled = True
        with self.lock:
            self.state["message"] = "Stopping."
            self._bump(True)
        return {"ok": True}

    def _guard(self, fn, mode):
        try:
            fn()
            with self.lock:
                if self.cancelled:
                    self.state["partial"] = True
                    self.state["message"] = "Stopped. The lists show only what was measured before the stop."
                else:
                    self.state["message"] = "Scan finished."
                    self.state["scannedAt"] = time.strftime("%Y-%m-%d %H:%M")
                    self.state["partial"] = False
        except Exception as exc:
            with self.lock:
                self.state["message"] = "The scan stopped on an error."
                self.errors.append({"path": mode, "message": str(exc)[:240]})
        finally:
            with self.lock:
                self.state["running"] = False
                self.state["current"] = ""
                self._bump(True)

    def _stop(self):
        return self.cancelled

    def _allow_root(self, path):
        with self.lock:
            self.allowed_roots.add(norm(path))

    def _allow_file(self, path):
        with self.lock:
            self.allowed_files.add(norm(path))

    def _publish_target(self, spec, total, eligible, count, ecount, status, error=""):
        item = {
            "id": spec["id"],
            "kind": spec["kind"],
            "label": spec["label"],
            "path": spec["path"],
            "group": spec["group"],
            "risk": spec["risk"],
            "why": spec["why"],
            "bytes": total,
            "eligible": eligible,
            "count": count,
            "eligibleCount": ecount,
            "status": status,
            "error": error,
            "older": spec.get("older"),
            "pattern": spec.get("pattern"),
        }
        with self.lock:
            self.catalog[item["id"]] = item
            self.targets = [t for t in self.targets if t["id"] != item["id"]]
            self.targets.append({k: item[k] for k in (
                "id", "label", "path", "group", "risk", "why", "bytes", "eligible",
                "count", "eligibleCount", "status", "error",
            )})
            self._bump(True)
        if status == "ready":
            self._allow_root(spec["path"])

    def _quick(self):
        with self.lock:
            self.files = [row for row in self.files if row.get("group") == "large"]
            for key, item in list(self.catalog.items()):
                if item.get("group") == "downloads" or item.get("kind") in ("aged-tree", "all-tree", "glob"):
                    self.catalog.pop(key, None)
            self.errors = []
            self.truncated.pop("downloads", None)
        self.note("", "Reading drives.")
        drives = list_drives()
        with self.lock:
            self.drives = drives
            self._bump(True)
        if self._stop():
            return
        self.note("", "Reading the Recycle Bin.")
        info = query_recycle()
        with self.lock:
            self.recycle_info = info
            self._bump(True)
        self.sense = storage_sense()
        self.health = physical_disks()
        with self.lock:
            self._bump(True)
        specs = self._specs()
        with self.lock:
            self.targets = []
            for spec in specs:
                self.catalog.pop(spec["id"], None)
        for spec in specs:
            if self._stop():
                return
            self.note(spec["path"], f"Measuring {spec['label']}")
            if not spec["path"] or not os.path.exists(spec["path"]):
                self._publish_target(spec, 0, 0, 0, 0, "missing")
                continue
            if self.is_protected(spec["path"]):
                self._publish_target(spec, 0, 0, 0, 0, "error", "This folder is protected.")
                continue
            try:
                total, eligible, count, ecount = self._tally(spec)
            except OSError as exc:
                self._publish_target(spec, 0, 0, 0, 0, "error", str(exc)[:240])
                continue
            self._publish_target(spec, total, eligible, count, ecount, "ready")
        if self._stop():
            return
        self._scan_downloads()
        self._remember_space()

    def _remember_space(self):
        drives = self.drives or list_drives()
        if not drives:
            return
        point = {
            "t": time.strftime("%Y-%m-%d"),
            "free": sum(d["free"] for d in drives),
            "used": sum(d["used"] for d in drives),
        }
        with self.lock:
            history = self.settings["history"]
            if history and history[-1].get("t") == point["t"]:
                history[-1] = point
            else:
                history.append(point)
            self.settings["history"] = history[-90:]
            self._save_settings()
            self._bump(True)

    def _specs(self):
        local = os.environ.get("LOCALAPPDATA", "")
        roaming = os.environ.get("APPDATA", "")
        home = os.path.expanduser("~")
        temp_days = self.settings["tempDays"]
        rows = []

        def add(**kwargs):
            path = kwargs.get("path") or ""
            if not path or not os.path.exists(path):
                return
            if self.is_protected(path):
                return
            kwargs.setdefault("older", None)
            kwargs.setdefault("pattern", None)
            rows.append(kwargs)

        add(
            id="temp-user", path=os.environ.get("TEMP", ""), kind="aged-tree", group="junk", risk="low",
            older=temp_days * 86400,
            label=f"Temp files older than {temp_days} days",
            why="Programs leave these behind. Files from the last saved number of days stay, so a program you are running keeps its temp files.",
        )
        add(
            id="crashdumps", path=os.path.join(local, "CrashDumps"), kind="aged-tree", group="junk", risk="review",
            older=14 * 86400, label="Crash dumps older than 14 days",
            why="A crash dump can contain data from the program that crashed. Recycling removes the dump, not the program.",
        )
        explorer = os.path.join(local, "Microsoft", "Windows", "Explorer")
        add(
            id="thumbs", path=explorer, kind="glob", pattern="thumbcache", group="junk", risk="review",
            label="Thumbnail cache",
            why="Windows rebuilds picture thumbnails. Explorer may be using these files, so a locked one stays put.",
        )
        add(
            id="inet-cache", path=os.path.join(local, "Microsoft", "Windows", "INetCache"),
            kind="all-tree", group="caches", risk="review", label="Legacy browser cache",
            why="Old Internet Explorer and some apps store pages here. Recycling makes those pages load again.",
        )
        add(
            id="d3d", path=os.path.join(local, "D3DSCache"), kind="all-tree", group="caches", risk="low",
            label="Direct3D shader cache",
            why="Windows rebuilds this graphics cache. Games may stutter once the first time they run.",
        )
        for sub, label in (("DXCache", "NVIDIA shader cache"), ("GLCache", "NVIDIA OpenGL cache")):
            add(
                id="nvidia-" + sub.lower(), path=os.path.join(local, "NVIDIA", sub),
                kind="all-tree", group="caches", risk="low", label=label,
                why="NVIDIA rebuilds this cache. A game may compile shaders again once.",
            )
        add(
            id="npm", path=os.path.join(local, "npm-cache"), kind="all-tree", group="dev", risk="low",
            label="npm cache",
            why="npm downloads these packages again the next time a project needs them. Projects themselves stay.",
        )
        add(
            id="pip", path=os.path.join(local, "pip", "Cache"), kind="all-tree", group="dev", risk="low",
            label="pip cache",
            why="pip downloads these packages again the next time you install them.",
        )
        cargo = os.path.join(home, ".cargo", "registry", "cache")
        add(
            id="cargo", path=cargo, kind="all-tree", group="dev", risk="review",
            label="Cargo download cache",
            why="Rust downloads these crate files again on the next build. Your source stays.",
        )
        claude = os.path.join(home, ".claude")
        claude_low = (
            ("cache", "Claude cache", "Claude rebuilds this cache."),
            ("debug", "Claude debug logs", "Debug logs. Settings and skills are not in this folder."),
            ("telemetry", "Claude telemetry", "Telemetry files. Settings and skills are not in this folder."),
            ("shell-snapshots", "Claude shell snapshots", "Saved shell output from old sessions."),
            ("session-env", "Claude session environment", "Environment dumps from old sessions."),
            ("notifier-events", "Claude notification records", "Old notification records."),
        )
        for sub, label, why in claude_low:
            add(id="claude-" + sub, path=os.path.join(claude, sub), kind="all-tree", group="dev", risk="low", label=label, why=why)
        claude_review = (
            ("file-history", "Claude file history", "Copies of files Claude edited. The current files on disk stay. These copies go."),
            ("backups", "Claude backups", "Backups Claude kept. Recycling removes the backup, not the original project."),
            ("todos", "Claude todo lists", "Todo lists Claude stored."),
        )
        for sub, label, why in claude_review:
            add(id="claude-" + sub, path=os.path.join(claude, sub), kind="all-tree", group="dev", risk="review", label=label, why=why)
        add(
            id="claude-transcripts", path=os.path.join(claude, "projects"), kind="glob", pattern=".jsonl",
            group="dev", risk="review", label="Claude session transcripts",
            why="Chat transcripts. Skills, settings, and sign-in files are not these .jsonl files. Recycling a transcript loses that chat.",
        )
        add(
            id="claude-local-logs", path=os.path.join(local, "Claude", "logs"), kind="all-tree",
            group="dev", risk="low", label="Claude app logs",
            why="Log files for the Claude desktop app. The app itself stays.",
        )
        codex = os.path.join(home, ".codex")
        for sub, label in (("tmp", "Codex temp"), (".tmp", "Codex temp files"), ("cache", "Codex cache")):
            add(
                id="codex-" + slug(sub), path=os.path.join(codex, sub), kind="all-tree", group="dev", risk="low",
                label=label, why="Codex rebuilds this. Sessions, memory, and auth.json stay.",
            )
        grok = os.path.join(home, ".grok")
        add(id="grok-logs", path=os.path.join(grok, "logs"), kind="all-tree", group="dev", risk="low",
            label="Grok logs", why="Log files. Sessions and memory stay.")
        add(id="grok-market", path=os.path.join(grok, "marketplace-cache"), kind="all-tree", group="dev", risk="review",
            label="Grok plugin cache", why="Plugin files that can be downloaded again. Installed settings stay.")
        cursor = os.path.join(roaming, "Cursor")
        for sub, risk, label, why in (
            ("logs", "low", "Cursor logs", "Editor log files."),
            ("Crashpad", "low", "Cursor crash reports", "Crash reports. The editor stays."),
            ("Cache", "review", "Cursor cache", "The editor rebuilds this cache. Open editors may recreate it."),
            ("Code Cache", "review", "Cursor code cache", "The editor rebuilds this cache."),
            ("GPUCache", "review", "Cursor GPU cache", "The editor rebuilds this graphics cache."),
            ("CachedData", "review", "Cursor cached app data", "Cached editor files. They download again."),
            ("CachedExtensionVSIXs", "review", "Cursor extension packages", "Extension installers. Installed extensions stay."),
        ):
            add(id="cursor-" + slug(sub), path=os.path.join(cursor, sub), kind="all-tree", group="caches" if risk == "review" and "log" not in label.lower() and "crash" not in label.lower() else "dev",
                risk=risk, label=label, why=why)
        for rel, name in (
            ("Google\\Chrome\\User Data", "Chrome"),
            ("Microsoft\\Edge\\User Data", "Edge"),
            ("BraveSoftware\\Brave-Browser\\User Data", "Brave"),
        ):
            root = os.path.join(local, rel)
            if not os.path.isdir(root):
                continue
            try:
                profiles = os.listdir(root)
            except OSError:
                continue
            for profile in profiles:
                if profile != "Default" and not profile.startswith("Profile"):
                    continue
                for sub in ("Cache", "Code Cache", "GPUCache"):
                    path = os.path.join(root, profile, sub)
                    who = name if profile == "Default" else f"{name} {profile}"
                    add(
                        id=f"browser-{slug(who)}-{slug(sub)}", path=path, kind="all-tree", group="caches", risk="review",
                        label=f"{who} {sub}",
                        why=f"{name} rebuilds this cache. You stay signed in. Pages may load slower once.",
                    )
        return rows

    def _tally(self, spec):
        total = eligible = count = ecount = 0
        older = spec.get("older")
        pattern = (spec.get("pattern") or "").lower()
        now = time.time()
        stack = [spec["path"]]
        while stack:
            if self._stop():
                break
            current = stack.pop()
            self.note(current)
            try:
                entries = list(os.scandir(current))
            except OSError as exc:
                self.add_error(current, exc)
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_reparse(st):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if self.is_protected(entry.path):
                        continue
                    if entry.name.casefold() in SKIP_WALK:
                        continue
                    stack.append(entry.path)
                    continue
                if self.is_protected(entry.path):
                    continue
                if pattern and pattern not in entry.name.lower():
                    continue
                total += st.st_size
                count += 1
                old_enough = older is None or (now - st.st_mtime) >= older
                if old_enough:
                    eligible += st.st_size
                    ecount += 1
        return total, eligible, count, ecount

    def _scan_downloads(self):
        root = folder("downloads", "Downloads")
        if not root:
            return
        cutoff = time.time() - self.settings["downloadDays"] * 86400
        minimum = self.settings["largeMinMB"] * 1024 * 1024
        found = 0
        stack = [root]
        while stack:
            if self._stop():
                return
            current = stack.pop()
            self.note(current, "Reading old downloads")
            try:
                entries = list(os.scandir(current))
            except OSError as exc:
                self.add_error(current, exc)
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_reparse(st):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if self.is_protected(entry.path) or entry.name.casefold() in SKIP_WALK:
                        continue
                    if entry.name.casefold() == "node_modules":
                        self._add_bundle(entry.path, "review", "Installed packages inside Downloads. The next install downloads them again.")
                        continue
                    stack.append(entry.path)
                    continue
                if self.is_protected(entry.path):
                    continue
                if st.st_size >= minimum:
                    self._add_file(entry.path, st, "large", "review", "A large file in Downloads.")
                if st.st_mtime <= cutoff:
                    if found >= LIST_CAP:
                        self.truncated["downloads"] = True
                        continue
                    self._add_file(
                        entry.path, st, "downloads", "review",
                        f"In Downloads, and last changed more than {self.settings['downloadDays']} days ago.",
                    )
                    found += 1

    def _add_file(self, path, st, group, risk, why):
        item_id = self._next_id("f")
        record = {
            "id": item_id,
            "kind": "file",
            "label": os.path.basename(path),
            "name": os.path.basename(path),
            "path": path,
            "group": group,
            "risk": "review" if self.is_guarded(path) else risk,
            "why": why,
            "bytes": int(st.st_size),
            "mtime": int(st.st_mtime),
            "eligible": int(st.st_size),
            "paths": [path],
        }
        if self.is_guarded(path):
            record["why"] = why + " This file is in a personal folder."
        with self.lock:
            self.catalog[item_id] = record
            self.allowed_files.add(norm(path))
            if group == "large":
                self.files = [row for row in self.files if norm(row["path"]) != norm(path) or row["group"] != "large"]
                self.files.append(self._public_file(record))
                larges = [row for row in self.files if row["group"] == "large"]
                if len(larges) > LARGE_CAP:
                    drop = sorted(larges, key=lambda row: row["bytes"])[:len(larges) - LARGE_CAP]
                    drop_ids = {row["id"] for row in drop}
                    self.files = [row for row in self.files if row["id"] not in drop_ids]
                    for row in drop:
                        self.catalog.pop(row["id"], None)
            else:
                self.files.append(self._public_file(record))
            self._bump()

    def _public_file(self, record):
        return {k: record[k] for k in ("id", "name", "path", "group", "risk", "why", "bytes", "mtime")}

    def _add_bundle(self, path, risk, why):
        with self.lock:
            if any(norm(row["path"]) == norm(path) for row in self.bundles):
                return
            if len(self.bundles) >= BUNDLE_CAP:
                self.truncated["bundles"] = True
                return
        total, count = self._sum(path)
        if total < 1024 * 1024:
            return
        item_id = self._next_id("b")
        label = os.path.basename(path)
        parent = os.path.basename(os.path.dirname(path))
        record = {
            "id": item_id, "kind": "bundle", "label": f"{label} in {parent}", "path": path,
            "group": "dev", "risk": risk, "why": why, "bytes": total, "eligible": total,
            "count": count, "paths": [path],
        }
        with self.lock:
            self.catalog[item_id] = record
            self.allowed_roots.add(norm(path))
            self.bundles.append({k: record[k] for k in ("id", "label", "path", "group", "risk", "why", "bytes", "count")})
            self._bump(True)

    def _sum(self, path):
        total = count = 0
        stack = [path]
        while stack:
            if self._stop():
                break
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except OSError as exc:
                self.add_error(current, exc)
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_reparse(st):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    stack.append(entry.path)
                else:
                    total += st.st_size
                    count += 1
        return total, count

    def _disk(self):
        with self.lock:
            self.files = [row for row in self.files if row.get("group") != "large"]
            for row in list(self.catalog):
                item = self.catalog[row]
                if item.get("group") == "large" or item.get("kind") in ("bundle", "dupe-file"):
                    self.catalog.pop(row, None)
            self.bundles = []
            self.dupes = []
            self.truncated.pop("large", None)
            self.truncated.pop("dupes", None)
            self.truncated.pop("bundles", None)
        self.note("", "Scanning folders for large files and duplicates. Nothing is deleted.")
        personal = [p for p in (
            folder("downloads", "Downloads"),
            folder("desktop", "Desktop"),
            folder("documents", "Documents"),
            folder("pictures", "Pictures"),
            folder("videos", "Videos"),
            folder("music", "Music"),
        ) if p]
        by_size = defaultdict(list)
        counter = [0]
        for root in personal:
            self._walk_collect(root, by_size, personal_dupe=True, counter=counter)
            if self._stop():
                break
        if not self._stop():
            self._finish_dupes(by_size)
        if self._stop():
            return
        home = os.path.expanduser("~")
        self._walk_collect(home, None, personal_dupe=False, skip_roots=personal)
        if self._stop():
            return
        for drive in self.drives or list_drives():
            if self._stop():
                return
            root = f"{drive['letter']}:\\"
            try:
                entries = list(os.scandir(root))
            except OSError as exc:
                self.add_error(root, exc)
                continue
            for entry in entries:
                if self._stop():
                    return
                try:
                    if entry.is_symlink() or not entry.is_dir(follow_symlinks=False):
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_reparse(st):
                    continue
                if entry.name.casefold() in QUIET_DIRS:
                    continue
                if self.is_protected(entry.path) or under(entry.path, home):
                    continue
                self._walk_collect(entry.path, None, personal_dupe=False, skip_roots=[])

    def _walk_collect(self, root, by_size, personal_dupe, skip_roots=None, counter=None):
        skip_roots = skip_roots or []
        minimum = self.settings["largeMinMB"] * 1024 * 1024
        stack = [root]
        while stack:
            if self._stop():
                return
            current = stack.pop()
            if any(under(current, skipped) and norm(current) != norm(root) for skipped in skip_roots):
                continue
            self.note(current, "Scanning folders")
            try:
                entries = list(os.scandir(current))
            except OSError as exc:
                self.add_error(current, exc)
                continue
            for entry in entries:
                try:
                    if entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_reparse(st):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    folded = entry.name.casefold()
                    if folded in QUIET_DIRS or folded in SKIP_WALK or self.is_protected(entry.path):
                        continue
                    if any(under(entry.path, skipped) for skipped in skip_roots):
                        continue
                    if folded == "node_modules":
                        self._add_bundle(entry.path, "review", "Installed packages. The next install downloads them again. The project source stays.")
                        continue
                    if folded == ".next":
                        self._add_bundle(entry.path, "review", "A Next.js build folder. The next build recreates it.")
                        continue
                    if folded == "__pycache__":
                        self._add_bundle(entry.path, "low", "Python bytecode. The next run rebuilds it.")
                        continue
                    if folded == "target" and (
                        os.path.isfile(os.path.join(entry.path, ".rustc_info.json"))
                        or os.path.isfile(os.path.join(entry.path, "CACHEDIR.TAG"))
                    ):
                        self._add_bundle(entry.path, "review", "A Rust build folder. The next build recreates it. Source stays.")
                        continue
                    stack.append(entry.path)
                    continue
                if self.is_protected(entry.path):
                    continue
                if st.st_size >= minimum:
                    where = "Personal folder." if self.is_guarded(entry.path) else "Large file outside the protected Windows folders."
                    self._add_file(entry.path, st, "large", "review", where)
                if personal_dupe and MIN_DUPE <= st.st_size <= 4 * 1024 ** 3:
                    if counter is not None:
                        counter[0] += 1
                        if counter[0] > 20000:
                            with self.lock:
                                self.truncated["dupes"] = True
                            personal_dupe = False
                            continue
                    by_size[st.st_size].append((entry.path, int(st.st_mtime), int(st.st_size)))

    def _finish_dupes(self, by_size):
        groups = 0
        for size, rows in by_size.items():
            if self._stop() or groups >= DUPE_CAP:
                if groups >= DUPE_CAP:
                    self.truncated["dupes"] = True
                break
            if len(rows) < 2 or len(rows) > HASH_GROUP_MAX:
                continue
            buckets = defaultdict(list)
            for path, mtime, nbytes in rows:
                try:
                    digest = _sample_hash(path, nbytes)
                except OSError:
                    continue
                buckets[digest].append((path, mtime, nbytes))
            for digest, copies in buckets.items():
                if len(copies) < 2 or groups >= DUPE_CAP:
                    continue
                newest = max(copies, key=lambda row: (row[1], row[0]))
                files = []
                for path, mtime, nbytes in sorted(copies, key=lambda row: row[0]):
                    item_id = self._next_id("f")
                    keep = path == newest[0]
                    record = {
                        "id": item_id, "kind": "file", "label": os.path.basename(path),
                        "name": os.path.basename(path), "path": path, "group": "dupes",
                        "risk": "review", "bytes": nbytes, "mtime": mtime, "eligible": 0 if keep else nbytes,
                        "paths": [path],
                        "why": "Same size and the same first and last 64 KB. This is not a full-file check. The newest copy is kept unless you select it yourself.",
                    }
                    with self.lock:
                        self.catalog[item_id] = record
                        self.allowed_files.add(norm(path))
                    files.append({
                        "id": item_id, "name": record["name"], "path": path, "bytes": nbytes,
                        "mtime": mtime, "keep": keep, "risk": "review", "why": record["why"],
                    })
                groups += 1
                with self.lock:
                    self.dupes.append({
                        "id": "g" + digest[:12],
                        "bytes": size,
                        "match": "sample",
                        "digest": digest,
                        "files": files,
                    })
                    self._bump()

    def confirm_dupe(self, group_id):
        import hashlib
        with self.lock:
            group = next((g for g in self.dupes if g["id"] == group_id), None)
            if not group:
                return {"ok": False, "error": "That group is no longer in the list."}
            files = list(group["files"])
        digests = {}
        for row in files:
            if self._stop():
                break
            h = hashlib.blake2b(digest_size=16)
            try:
                with open(row["path"], "rb") as handle:
                    while True:
                        chunk = handle.read(1024 * 1024)
                        if not chunk:
                            break
                        h.update(chunk)
            except OSError as exc:
                return {"ok": False, "error": f"Could not read {row['name']}: {exc}"}
            digests.setdefault(h.hexdigest(), []).append(row)
        same = len(digests) == 1
        with self.lock:
            for group in self.dupes:
                if group["id"] == group_id:
                    group["match"] = "full" if same else "different"
                    group["why"] = "Every byte matches." if same else "The sample matched, but the full files do not."
            self._bump(True)
        return {"ok": True, "match": "full" if same else "different"}

    def prepare(self, ids):
        if not isinstance(ids, list) or not ids:
            return {"ok": False, "error": "Select something first."}
        items = []
        missing = []
        for item_id in ids:
            item = self.catalog.get(item_id)
            if not item:
                missing.append(str(item_id))
            else:
                items.append(item)
        if missing:
            return {"ok": False, "error": "That selection is from an older scan. Scan again, then choose."}
        est_bytes = 0
        est_count = 0
        names = []
        for item in items:
            if item["kind"] == "file":
                est_bytes += int(item.get("bytes") or 0)
                est_count += 1
            else:
                est_bytes += int(item.get("eligible") if item.get("eligible") is not None else item.get("bytes") or 0)
                est_count += int(item.get("eligibleCount") or item.get("count") or 1)
            if len(names) < 8:
                names.append(item.get("label") or item.get("name") or item.get("path"))
        paths_for_guard = []
        for item in items:
            if item.get("path"):
                paths_for_guard.append(item["path"])
            paths_for_guard.extend(item.get("paths") or [])
        blocked = [p for p in paths_for_guard if self.is_protected(p)]
        if blocked:
            return {
                "ok": False,
                "error": "That selection includes a protected path. Nothing was recycled.",
                "blocked": blocked[:8],
            }
        if est_count <= 0 or est_bytes < 0:
            return {"ok": False, "error": "Nothing in this selection is eligible. Files newer than the age limit stay."}
        needs = (
            any(item.get("risk") != "low" for item in items)
            or any(self.is_guarded(p) for p in paths_for_guard)
            or est_bytes > TWO_GB
            or est_count > 200
        )
        return {
            "ok": True,
            "count": est_count,
            "bytes": est_bytes,
            "needsWord": needs,
            "names": names,
            "more": max(0, len(items) - len(names)),
            "risk": "low" if not needs else "review",
        }

    def recycle(self, ids, word=""):
        plan = self.prepare(ids)
        if not plan.get("ok"):
            return plan
        if plan["needsWord"] and word != "RECYCLE":
            return {"ok": False, "error": "Type RECYCLE to confirm this. Nothing was recycled."}
        paths = self.expand(ids)
        refused = [p for p in paths if self.is_protected(p) or not self._path_allowed(p)]
        if refused:
            return {
                "ok": False,
                "error": "A path in this selection is protected or was not part of the scan. Nothing was recycled.",
                "blocked": refused[:8],
            }
        if not paths:
            return {"ok": False, "error": "Nothing in this selection is old enough to recycle."}
        if len(paths) > FILE_CAP:
            return {
                "ok": False,
                "error": f"This selection is {len(paths)} files. Luwag recycles at most {FILE_CAP} in one pass. Narrow the selection.",
            }
        with self.lock:
            self.state["running"] = True
            self.state["phase"] = "recycle"
            self.state["message"] = f"Recycling {len(paths)} items."
            self._bump(True)
        try:
            recycled, failed, missing = self._send(paths)
        finally:
            with self.lock:
                self.state["running"] = False
                self.state["phase"] = "idle"
                self.state["message"] = "Recycle finished."
                self._bump(True)
        info = query_recycle()
        with self.lock:
            self.recycle_info = info
            self._bump(True)
        return {
            "ok": failed == [] or recycled > 0,
            "recycled": recycled,
            "missing": missing,
            "failed": failed[:12],
            "failedCount": len(failed),
            "bytes": plan["bytes"],
        }

    def expand(self, ids):
        paths = []
        for item_id in ids:
            item = self.catalog.get(item_id)
            if not item:
                continue
            kind = item["kind"]
            if kind in ("file", "bundle"):
                paths.extend(item.get("paths") or [item["path"]])
            elif kind == "aged-tree":
                paths.extend(self._collect(item["path"], item.get("older"), None, FILE_CAP + 1))
            elif kind == "all-tree":
                paths.extend(self._collect(item["path"], None, None, FILE_CAP + 1))
            elif kind == "glob":
                paths.extend(self._collect(item["path"], None, item.get("pattern"), FILE_CAP + 1))
        seen = set()
        out = []
        for path in paths:
            key = norm(path)
            if key in seen:
                continue
            seen.add(key)
            out.append(os.path.abspath(path))
        return out

    def _collect(self, root, older, pattern, limit):
        now = time.time()
        found = []
        stack = [root]
        pattern = (pattern or "").lower()
        while stack and len(found) < limit:
            if self._stop():
                break
            current = stack.pop()
            try:
                entries = list(os.scandir(current))
            except OSError:
                continue
            for entry in entries:
                if len(found) >= limit:
                    break
                try:
                    if entry.is_symlink():
                        continue
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_reparse(st):
                    continue
                if entry.is_dir(follow_symlinks=False):
                    if self.is_protected(entry.path) or entry.name.casefold() in SKIP_WALK:
                        continue
                    stack.append(entry.path)
                    continue
                if self.is_protected(entry.path):
                    continue
                if pattern and pattern not in entry.name.lower():
                    continue
                if older is not None and (now - st.st_mtime) < older:
                    continue
                found.append(entry.path)
        return found

    def _path_allowed(self, path):
        key = norm(path)
        if key in self.allowed_files:
            return True
        return any(under(path, root) for root in list(self.allowed_roots))

    def _send(self, paths):
        from send2trash import send2trash
        recycled = 0
        missing = 0
        failed = []
        existing = []
        for path in paths:
            if os.path.exists(path):
                existing.append(path)
            else:
                missing += 1
        for start in range(0, len(existing), 80):
            chunk = existing[start:start + 80]
            self.note(chunk[0], f"Recycling {recycled + len(chunk)} of {len(existing)}")
            try:
                send2trash(chunk)
                recycled += len(chunk)
                continue
            except Exception:
                pass
            for path in chunk:
                try:
                    send2trash(path)
                    recycled += 1
                except Exception as exc:
                    failed.append({"path": path, "error": str(exc)[:180] or "Windows refused this file."})
        return recycled, failed, missing

    def empty_bin(self, word):
        if word != "EMPTY":
            return {"ok": False, "error": "Type EMPTY to empty the Recycle Bin. Nothing was removed."}
        shell32 = ctypes.windll.shell32
        shell32.SHEmptyRecycleBinW.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.DWORD]
        shell32.SHEmptyRecycleBinW.restype = ctypes.HRESULT
        hr = int(shell32.SHEmptyRecycleBinW(None, None, 0x1 | 0x4))
        info = query_recycle()
        with self.lock:
            self.recycle_info = info
            self._bump(True)
        if hr not in (0,):
            # Already empty, or a file was locked. Report the bin's new size either way.
            if info.get("count", 1) == 0 and not info.get("error"):
                return {"ok": True, "recycle": info}
            return {"ok": False, "error": f"Windows did not empty the bin ({hr:#x}).", "recycle": info}
        return {"ok": True, "recycle": info}

    def reveal(self, path):
        if not path or not isinstance(path, str):
            return {"ok": False, "error": "No path to show."}
        full = os.path.abspath(path)
        if not os.path.exists(full):
            return {"ok": False, "error": "That item is no longer there."}
        subprocess.Popen(f'explorer /select,"{full}"', creationflags=CREATE_NO_WINDOW)
        return {"ok": True}

    def open_bin(self):
        os.startfile("shell:RecycleBinFolder")
        return {"ok": True}

    def open_storage_settings(self):
        os.startfile("ms-settings:storagesense")
        return {"ok": True}

    def copy_text(self, text):
        if not isinstance(text, str):
            text = ""
        subprocess.run(["clip"], input=text, text=True, check=False, creationflags=CREATE_NO_WINDOW)
        return {"ok": True}

    def summary(self):
        snap = self.snapshot()
        lines = ["Luwag scan"]
        if snap["scannedAt"]:
            lines.append(f"Measured {snap['scannedAt']}")
        for drive in snap["drives"]:
            lines.append(
                f"{drive['letter']}: {fmt_bytes(drive['used'])} used, {fmt_bytes(drive['free'])} free, of {fmt_bytes(drive['total'])}"
            )
        lines.append("")
        for target in sorted(snap["targets"], key=lambda row: row.get("eligible") or 0, reverse=True):
            if target.get("status") != "ready":
                continue
            lines.append(f"{target['label']}: {fmt_bytes(target['eligible'])} eligible, {target['risk']}, {target['path']}")
        return "\n".join(lines)

    def export_csv(self):
        snap = self.snapshot()
        name = time.strftime("Luwag-%Y%m%d-%H%M.csv")
        dest_dir = folder("downloads", "Downloads") or self.data_dir
        dest = os.path.join(dest_dir, name)
        rows = []
        for target in snap["targets"]:
            rows.append(("target", target.get("group"), target.get("label"), target.get("path"), target.get("eligible") or 0, target.get("risk"), target.get("why")))
        for row in snap["files"]:
            rows.append((row.get("group"), row.get("group"), row.get("name"), row.get("path"), row.get("bytes") or 0, row.get("risk"), row.get("why")))
        for row in snap["bundles"]:
            rows.append(("bundle", "dev", row.get("label"), row.get("path"), row.get("bytes") or 0, row.get("risk"), row.get("why")))
        for group in snap["dupes"]:
            for row in group["files"]:
                rows.append(("duplicate", "dupes", row.get("name"), row.get("path"), row.get("bytes") or 0, "review", "Same size and sample" if group.get("match") != "full" else "Full file match"))
        try:
            with open(dest, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(("kind", "group", "label", "path", "bytes", "risk", "why"))
                writer.writerows(rows)
        except OSError:
            dest = os.path.join(self.data_dir, name)
            with open(dest, "w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(("kind", "group", "label", "path", "bytes", "risk", "why"))
                writer.writerows(rows)
        return {"ok": True, "path": dest, "rows": len(rows)}


def _sample_hash(path, size):
    import hashlib
    digest = hashlib.blake2b(digest_size=16)
    with open(path, "rb") as handle:
        digest.update(handle.read(65536))
        if size > 65536:
            handle.seek(max(0, size - 65536))
            digest.update(handle.read(65536))
    return digest.hexdigest()
