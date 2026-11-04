# Luwag Storage

See what is using this Windows PC, then send the files you choose to the Recycle Bin.

The first screen is the overview: free space on each drive, then the folders Luwag measured.

## Features

- Drive totals, Storage Sense, and the physical disk come from this PC. The numbers are measured, not samples.
- Junk, caches, dev leftovers, large files, duplicates, and old downloads.
- Clay pictures for folders, photos, video, audio, archives, code, and the other kinds.
- Recycle Bin only. Emptying the bin is a separate step and asks for the word EMPTY.
- Windows, Program Files, sign-in files, and Git history stay protected. Desktop, Documents, Pictures, Videos, Music, and OneDrive ask you to type RECYCLE.

## Install

Luwag is a Windows app. There is no Android build.

1. Install the [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/) if Windows does not already have it. Windows 11 usually does.
2. Run `Luwag-Setup.exe` from the release. It installs for the current user and does not ask for administrator.
3. Or unzip `Luwag-windows.zip` and run `Luwag.exe`.

## Build

```text
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --windowed --name Luwag --icon ui/models/logo.ico --add-data "ui;ui" --collect-all webview --collect-all pythonnet app.py
```

Python 3.14, on Windows. `python -m unittest` from this folder runs the engine tests. Those tests do not scan the PC and do not empty the Recycle Bin.

## Stack

Python, pywebview (WebView2), send2trash. The window matches the LodiSave Gallery layout: left nav, list, preview, and a custom caption.

## License

MIT. See [LICENSE](LICENSE).
