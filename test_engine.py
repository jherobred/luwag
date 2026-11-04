"""Safety checks for Luwag. These never empty the Recycle Bin and never scan the PC."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import time
import unittest

import engine
from engine import TWO_GB, Engine, folder, norm, under


def contrast(a, b):
    def channel(value):
        value = value / 255
        if value <= 0.04045:
            return value / 12.92
        return ((value + 0.055) / 1.055) ** 2.4

    def lum(hex_color):
        h = hex_color.lstrip("#")
        red, green, blue = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        return 0.2126 * channel(red) + 0.7152 * channel(green) + 0.0722 * channel(blue)

    hi, lo = sorted((lum(a), lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


class EngineTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="luwag-test-")
        self.engine = Engine(data_dir=os.path.join(self.tmp, "data"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def file_item(self, path, risk="low", nbytes=10):
        return {
            "id": "f-test",
            "kind": "file",
            "label": os.path.basename(path),
            "name": os.path.basename(path),
            "path": path,
            "group": "junk",
            "risk": risk,
            "why": "test",
            "bytes": nbytes,
            "eligible": nbytes,
            "paths": [path],
        }

    def test_under_does_not_treat_windows_old_as_windows(self):
        windir = os.environ.get("WINDIR") or r"C:\Windows"
        self.assertTrue(under(os.path.join(windir, "System32"), windir))
        self.assertTrue(under(windir, windir))
        self.assertFalse(under(windir + ".old\\file.txt", windir))

    def test_protected_and_guarded(self):
        windir = os.environ["WINDIR"]
        self.assertTrue(self.engine.is_protected(windir))
        self.assertTrue(self.engine.is_protected("C:\\"))
        self.assertFalse(self.engine.is_protected(os.path.join(windir + ".old", "file.txt")))
        self.assertTrue(self.engine.is_protected(os.path.join(self.tmp, ".ssh", "id_ed25519")))
        self.assertTrue(self.engine.is_protected(os.path.join(self.tmp, "Login Data")))
        docs = folder("documents", "Documents")
        self.assertTrue(docs)
        self.assertTrue(self.engine.is_guarded(os.path.join(docs, "notes.txt")))
        self.assertFalse(self.engine.is_guarded(os.path.join(self.tmp, "notes.txt")))

    def test_tally_skips_new_files_and_ssh(self):
        root = os.path.join(self.tmp, "cache")
        os.makedirs(os.path.join(root, ".ssh"))
        old = os.path.join(root, "old.tmp")
        new = os.path.join(root, "new.tmp")
        hidden = os.path.join(root, ".ssh", "id")
        for path, text in ((old, "old-bytes"), (new, "new"), (hidden, "secret-bytes")):
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(text)
        stamp = time.time() - 10 * 86400
        os.utime(old, (stamp, stamp))
        total, eligible, count, ecount = self.engine._tally({"path": root, "older": 7 * 86400})
        self.assertEqual(count, 2)
        self.assertEqual(ecount, 1)
        self.assertEqual(eligible, os.path.getsize(old))
        self.assertGreater(total, eligible)

    def test_prepare_rules(self):
        path = os.path.join(self.tmp, "keep.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("keep")
        low = self.file_item(path)
        self.engine.catalog["f-test"] = low
        plan = self.engine.prepare(["f-test"])
        self.assertTrue(plan["ok"])
        self.assertFalse(plan["needsWord"])
        self.assertFalse(self.engine.prepare([])["ok"])
        self.assertFalse(self.engine.prepare(["missing"])["ok"])

        review = dict(low)
        review["risk"] = "review"
        self.engine.catalog["f-test"] = review
        self.assertTrue(self.engine.prepare(["f-test"])["needsWord"])

        self.engine.catalog["f-test"] = dict(low)
        self.engine.guarded = [self.tmp]
        self.assertTrue(self.engine.prepare(["f-test"])["needsWord"])
        self.engine.guarded = []

        huge = dict(low)
        huge["bytes"] = TWO_GB + 1
        self.engine.catalog["f-test"] = huge
        self.assertTrue(self.engine.prepare(["f-test"])["needsWord"])

        self.engine.catalog["tree"] = {
            "id": "tree", "kind": "all-tree", "label": "many", "path": self.tmp,
            "group": "junk", "risk": "low", "why": "test", "bytes": 10, "eligible": 10,
            "count": 201, "eligibleCount": 201, "paths": [self.tmp],
        }
        self.assertTrue(self.engine.prepare(["tree"])["needsWord"])

        blocked = self.file_item(os.path.join(os.environ["WINDIR"], "notepad.exe"))
        blocked["id"] = "blocked"
        self.engine.catalog["blocked"] = blocked
        self.engine.allowed_files.add(norm(blocked["path"]))
        refused = self.engine.prepare(["blocked"])
        self.assertFalse(refused["ok"])
        self.assertIn("protected", refused["error"].lower())
        self.assertFalse(self.engine.recycle(["blocked"], "RECYCLE")["ok"])
        self.assertTrue(os.path.exists(blocked["path"]))

    def test_recycle_refuses_unlisted_and_wrong_word(self):
        path = os.path.join(self.tmp, "stay.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("stay")
        self.engine.catalog["f-test"] = self.file_item(path, risk="review")
        denied = self.engine.recycle(["f-test"], "RECYCLE")
        self.assertFalse(denied["ok"])
        self.assertTrue(os.path.exists(path))
        self.engine.allowed_files.add(norm(path))
        wrong = self.engine.recycle(["f-test"], "recycle")
        self.assertFalse(wrong["ok"])
        self.assertTrue(os.path.exists(path))

    def test_recycle_refuses_over_cap_without_deleting(self):
        root = os.path.join(self.tmp, "many")
        os.makedirs(root)
        for index in range(5):
            with open(os.path.join(root, f"f{index}.txt"), "w", encoding="utf-8") as handle:
                handle.write("x")
        self.engine.catalog["cap"] = {
            "id": "cap", "kind": "all-tree", "label": "many", "path": root,
            "group": "junk", "risk": "low", "why": "test", "bytes": 5, "eligible": 5,
            "count": 5, "eligibleCount": 5, "paths": [root],
        }
        self.engine.allowed_roots.add(norm(root))
        old = engine.FILE_CAP
        engine.FILE_CAP = 3
        try:
            result = self.engine.recycle(["cap"], "")
        finally:
            engine.FILE_CAP = old
        self.assertFalse(result["ok"])
        self.assertIn("3", result["error"])
        for index in range(5):
            self.assertTrue(os.path.exists(os.path.join(root, f"f{index}.txt")))

    def test_empty_bin_requires_the_word(self):
        before = engine.query_recycle()
        result = self.engine.empty_bin("empty")
        after = engine.query_recycle()
        self.assertFalse(result["ok"])
        if not before.get("error") and not after.get("error"):
            self.assertEqual(before["count"], after["count"])

    def test_recycle_roundtrip_restores_the_file(self):
        name = "luwag-selftest-delete-me.txt"
        path = os.path.join(self.tmp, name)
        with open(path, "w", encoding="utf-8") as handle:
            handle.write("luwag test")
        self.engine.catalog["f-test"] = self.file_item(path)
        self.engine.allowed_files.add(norm(path))
        result = self.engine.recycle(["f-test"], "")
        self.assertTrue(result["ok"], result)
        self.assertGreaterEqual(result["recycled"], 1)
        self.assertFalse(os.path.exists(path))
        try:
            self.assertTrue(self.restore(name, path))
        finally:
            if os.path.exists(path):
                os.remove(path)

    def restore(self, name, path):
        stem = name[:-4]
        script = (
            "$shell = New-Object -ComObject Shell.Application; "
            "$bin = $shell.NameSpace(10); "
            "$item = $null; "
            "foreach ($candidate in @($bin.Items())) { "
            f"if ($candidate.Name -like '{stem}*') {{ $item = $candidate; break }} "
            "}; "
            "if ($null -eq $item) { Write-Output MISSING; exit 2 }; "
            "$verb = $null; "
            "foreach ($v in @($item.Verbs())) { if ($v.Name -match 'estore') { $verb = $v; break } }; "
            "if ($null -eq $verb) { Write-Output NOVERB; exit 3 }; "
            "$verb.DoIt(); Write-Output RESTORED"
        )
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(proc.returncode, 0, (proc.stdout or "") + (proc.stderr or ""))
        for _ in range(20):
            if os.path.exists(path):
                return True
            time.sleep(0.25)
        return False

    def test_onboarding_flag_starts_off(self):
        self.assertFalse(self.engine.snapshot()["settings"]["onboarded"])
        result = self.engine.update_settings({"onboarded": True, "motion": True})
        self.assertTrue(result["ok"])
        self.assertTrue(self.engine.snapshot()["settings"]["onboarded"])
        self.assertTrue(self.engine.snapshot()["settings"]["motion"])
        self.engine.update_settings({"onboarded": "yes", "motion": False})
        self.assertFalse(self.engine.snapshot()["settings"]["onboarded"])
        self.assertFalse(self.engine.snapshot()["settings"]["motion"])

    def test_unknown_scan_does_not_start(self):
        result = self.engine.start("wipe")
        self.assertFalse(result["ok"])
        self.assertFalse(self.engine.state["running"])

    def test_text_contrast(self):
        pairs = [
            ("#151413", "#F7F6F4"),
            ("#66645F", "#F7F6F4"),
            ("#66645F", "#E5E3DF"),
            ("#FFFFFF", "#B84C0C"),
            ("#C2362B", "#EFEEEB"),
            ("#FF8A7E", "#151413"),
            ("#FF8A3D", "#151413"),
            ("#F4F3F1", "#111113"),
            ("#A3A19C", "#111113"),
            ("#A3A19C", "#2C2C30"),
            ("#0F0F10", "#FF8A3D"),
            ("#FF6B5E", "#222225"),
            ("#3DD68C", "#111113"),
            ("#1A7F4B", "#F7F6F4"),
        ]
        for left, right in pairs:
            self.assertGreaterEqual(contrast(left, right), 4.5, f"{left} on {right}")


if __name__ == "__main__":
    unittest.main()
