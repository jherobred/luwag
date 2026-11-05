# Luwag Storage

See what is using storage, then set aside the files you choose.

On Windows, chosen files go to the Recycle Bin. On Android, Luwag copies a file into the app and removes the original only after that copy matches. Restore puts the file back.

The first screen is free space reported by the device. File lists come from a scan, not from guessed sizes.

## Features

- Drive totals, Storage Sense, and the physical disk come from this PC. The numbers are measured, not samples.
- Junk, caches, dev leftovers, large files, duplicates, and old downloads.
- Clay pictures for folders, photos, video, audio, archives, code, and the other kinds. They turn unless Settings sets Motion to Off, or Windows asks for less motion.
- A phone layout: `python app.py --phone`, or `Luwag-phone.bat`, or any window narrower than 760px. Overview, Junk, Caches, and Dev stay in the bottom bar. The rest are under More.
- The first launch walks through what the scan measures, which folders stay protected, and whether the pictures should move.
- Recycle Bin only. Emptying the bin is a separate step and asks for the word EMPTY.
- Windows, Program Files, sign-in files, and Git history stay protected. Desktop, Documents, Pictures, Videos, Music, and OneDrive ask you to type RECYCLE.
- Android reads free space with the system storage counters. Downloads, DCIM, Pictures, Movies, Music, and Documents are listed only after all-files access is allowed. Other apps' `Android/data` and `Android/obb` folders are skipped. Trash stays inside Luwag until you restore it or empty it.

## Install

Windows:

1. Install the [WebView2 runtime](https://developer.microsoft.com/microsoft-edge/webview2/) if Windows does not already have it. Windows 11 usually does.
2. Run `Luwag-Setup.exe` from the release. The setup window matches the app. It installs for the current user, adds a Start menu shortcut and a desktop shortcut, and does not ask for administrator.
3. Or unzip `Luwag-windows.zip` and run `Luwag.exe`.

Android:

1. Download `Luwag.apk` from the release and install it on a phone running Android 10 or newer.
2. The APK is signed with the debug key. It is a sideload build, not a Play Store build.
3. Allow all-files access when you want file lists. Free space is shown without that permission.

## Build

```text
python -m pip install -r requirements.txt
python -m pip install pyinstaller
python -m PyInstaller --noconfirm --windowed --name Luwag --icon ui/models/logo.ico --add-data "ui;ui" --collect-all webview --collect-all pythonnet app.py
```

Python 3.14, on Windows. `python -m unittest` from this folder runs the engine tests. Those tests do not scan the PC and do not empty the Recycle Bin.

The Android app is built from `android/` with JDK 17 and Android SDK platform 37.2:

```text
gradlew.bat assembleRelease test
```

`android/local.properties` points at the SDK on the build machine and is not in git. The release APK is `android/app/build/outputs/apk/release/app-release.apk`.

## Stack

Windows: Python, pywebview (WebView2), send2trash. The window matches the LodiSave Gallery layout: left nav, list, preview, and a custom caption.

Android: Kotlin and Jetpack Compose. It does not run the Windows scanner. The logo is the LodiSave hamster icon reskinned as a frog.

## License

MIT. See [LICENSE](LICENSE).
