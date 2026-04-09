# Plan A: Windows App via UTM Virtual Machine on Mac

## Context

The EVERGREEN desktop app is a Python/tkinter GUI currently packaged as a macOS `.app` via PyInstaller. The goal is to produce an identical Windows `.exe` version. This plan uses a Windows VM running on the Mac for development and testing.

The codebase is already mostly cross-platform: tkinter, platform-aware `_open_path()`, and `tkmacosx` fallback to `tk.Button`.

---

## One-Time Setup: Windows VM on Mac

1. **Download UTM** from `mac.getutm.app` (free, open-source Apple Silicon hypervisor)
2. **Download Windows 11 ARM64** VHDX from Microsoft (free evaluation, 90 days)
3. **Create VM** in UTM: Virtualize > Windows > attach VHDX, allocate 4+ GB RAM, 2+ cores
4. **Inside the VM install:**
   - Python 3.11 (ARM64) from python.org
   - Git for Windows
   - A code editor (VS Code recommended)
5. **Share project folder** via UTM shared directory, or clone the repo inside the VM

> Cost: $0. UTM is free. Windows evaluation is free for 90 days (can be re-armed).
> Alternative: Parallels ($100/yr) — faster, better integration, but paid.

---

## Code Changes Required

| File | Issue | Fix |
|------|-------|-----|
| `config.py` | EnergyPlus path hardcoded to `/Applications/EnergyPlus-25-2-0/` | Add Windows path: `C:\EnergyPlusV25-2-0\` via `platform.system()` branch |
| `gui.py` | Font `Helvetica Neue` missing on Windows | Add fallback: `Segoe UI` on Windows, `Helvetica Neue` on macOS |
| `gui.py` | `tkmacosx` import | Already has fallback to `tk.Button` — just verify |
| `gui.py:63` | `_open_path()` | Already has `os.startfile()` for Windows — OK |
| `build_app.py` | macOS-only PyInstaller flags | Add `platform.system()` branch for Windows build |
| **New:** `EVERGREEN_win.spec` | Windows PyInstaller spec | Based on `EVERGREEN.spec`, targeting `.exe` with `windowed=True` |
| **New:** `assets/icon.ico` | Windows icon format | Convert existing macOS `.icns` to `.ico` |

---

## Build Process (inside VM)

```powershell
# Install dependencies
pip install pyinstaller pymupdf pillow pydantic
pip install -e ".[gui]"

# Build
pyinstaller EVERGREEN_win.spec

# Run
dist\EVERGREEN\EVERGREEN.exe
```

---

## Distribution Options

- **Simple zip:** Zip `dist\EVERGREEN\` folder — user extracts and double-clicks `.exe`
- **Installer:** Use Inno Setup (free) to create a setup wizard `.exe`
- **Code signing:** Optional — purchase a Windows code-signing certificate to avoid SmartScreen warnings

---

## Optional: GitHub Actions CI for Automated Windows Builds

Add `.github/workflows/build-windows.yml` to build on `windows-latest` runner automatically on each release tag. This removes the need to keep the VM running for every build.

---

## Verification

1. Run `EVERGREEN.exe` in the Windows VM
2. Load Nili IDF + Tel Aviv EPW > click Run
3. Confirm Grade B result (same as macOS)
4. Confirm PDF viewer renders reports
5. Confirm log panel streams output in real time
6. Test file browser dialogs open correctly
