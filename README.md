# جلوه دسکتاپ

Desktop client for [jelveh.top](https://jelveh.top). The same Python app runs on Linux and Windows. Each platform has its own build output:

- Linux: `dist/linux/Jelveh/Jelveh`
- Windows: `dist/windows/Jelveh/Jelveh.exe`

The interface follows the site: right-to-left Persian, Vazirmatn, and the jet / ember palette (`#050505`, `#e50914`, `#ffc857`). Catalog data comes from `https://panel.jelveh.top/api/v1`. Playback uses the same `jelveh.top/media-proxy` path as the website and asks you to sign in first.

## Run from source

```bash
python3 -m pip install -r requirements.txt
python3 -m jelveh
```

## Build

On Linux:

```bash
./scripts/build_linux.sh
```

On Windows, in PowerShell:

```powershell
.\scripts\build_windows.ps1
```

A Windows build has to be made on Windows. Qt and the FFmpeg playback plugin are native libraries, so they cannot be cross-compiled from Linux.

## What you can do

- Browse the home feed, movies, and series
- Search titles and cast
- Open a title, read comments, and pick a quality (dubbed or subtitled)
- Stream in the built-in player
- Sign in with a phone number, save favorites, and keep playlists

Playback needs an account, the same way the website does. Continue-watching progress stays on this computer.
