# Plan B: Develop Directly on a Windows Intel PC

## Context

Same goal — produce a Windows `.exe` of the EVERGREEN app — but developed natively on a Windows PC with Intel CPU. This avoids VM overhead and ARM compatibility issues. You get native performance, native debugging, and direct access to the Windows version of EnergyPlus.

---

## Hardware & Software Setup

### What You Need
- **A Windows PC** (Intel x86_64, Windows 10 or 11)
  - Budget option: any used PC, even old laptops work fine for Python/tkinter dev
  - Or: a cloud Windows VM (Azure/AWS) if you don't want physical hardware
- **EnergyPlus 25.2 for Windows** — download the Windows installer from energyplus.net

### Install Dev Tools (one-time)
1. **Python 3.11** (x86_64) from python.org — check "Add to PATH" during install
2. **Git for Windows** from git-scm.com
3. **VS Code** (or any editor)
4. **Claude Code** CLI (if available on Windows) or use Claude via web

### Clone & Set Up Project
```powershell
git clone <your-repo-url>
cd ClaudeCodeProj
pip install -e ".[gui]"
pip install pyinstaller pymupdf pillow
```

---

## Code Changes Required

Same as Plan A — the code changes are identical regardless of where you develop:

| File | Issue | Fix |
|------|-------|-----|
| `config.py` | EnergyPlus path hardcoded to `/Applications/EnergyPlus-25-2-0/` | Add Windows path: `C:\EnergyPlusV25-2-0\` via `platform.system()` branch |
| `gui.py` | Font `Helvetica Neue` missing on Windows | Add fallback: `Segoe UI` on Windows |
| `gui.py` | `tkmacosx` import | Already has fallback — verify it works |
| `build_app.py` | macOS-only PyInstaller flags | Add `platform.system()` branch |
| **New:** `EVERGREEN_win.spec` | Windows PyInstaller spec | `.exe` with `windowed=True` |
| **New:** `assets/icon.ico` | Windows icon | Convert from macOS `.icns` |

---

## Development Workflow

### Daily workflow
```powershell
# Run GUI directly during development (no build needed)
python -m il_energy.gui

# Run CLI for quick tests
python -m il_energy run --idf path\to\file.idf --epw path\to\weather.epw --output-dir output\
```

### Build workflow
```powershell
# Build .exe
pyinstaller EVERGREEN_win.spec

# Test the built executable
dist\EVERGREEN\EVERGREEN.exe
```

### Keeping code in sync with Mac
- Use Git: develop on a `windows-support` branch, merge to `main`
- All platform-specific code uses `platform.system()` branches — both Mac and Windows builds come from the same codebase

---

## Advantages Over Plan A (VM Approach)

| | Plan A (VM on Mac) | Plan B (Native Windows PC) |
|---|---|---|
| **Performance** | Slower (VM overhead + ARM emulation for x86 apps) | Full native speed |
| **EnergyPlus** | ARM build may have quirks | Official Intel build, well-tested |
| **Debugging** | Harder (VM context switching) | Native — use VS Code debugger directly |
| **Build output** | ARM64 `.exe` (won't run on most user PCs which are Intel) | Intel x86_64 `.exe` (runs everywhere) |
| **Cost** | $0 (UTM free) | Cost of a PC (or ~$0.10/hr for cloud VM) |
| **Portability testing** | Can test both Mac + Windows on one machine | Need Mac separately for macOS builds |

> **Important note on Plan A:** UTM on Apple Silicon runs Windows ARM. PyInstaller in that VM produces an ARM64 `.exe`, which only runs on Windows ARM devices (rare). Most Windows users have Intel/AMD PCs. To produce an Intel `.exe` from a Mac, you'd need either this Plan B or GitHub Actions with `windows-latest` (Intel).

---

## Distribution

Same as Plan A:
- **Simple zip** of `dist\EVERGREEN\` folder
- **Inno Setup** installer (free)
- **Code signing** (optional, avoids SmartScreen warnings)

---

## Optional: GitHub Actions for Both Platforms

You can set up CI to build both macOS and Windows from the same repo:

```yaml
# .github/workflows/build.yml
jobs:
  build-mac:
    runs-on: macos-latest
    steps: [checkout, install python, pip install, pyinstaller EVERGREEN.spec]

  build-windows:
    runs-on: windows-latest    # Intel x86_64
    steps: [checkout, install python, pip install, pyinstaller EVERGREEN_win.spec]
```

This is the best long-term solution — push code, get both `.app` and `.exe` automatically.

---

## Verification

1. Run `python -m il_energy.gui` directly — confirm window opens with correct theme
2. Build with PyInstaller — run `EVERGREEN.exe`
3. Load Nili IDF + Tel Aviv EPW > Run
4. Confirm Grade B result matches macOS output
5. Confirm PDF viewer, log panel, file dialogs all work
6. Test on a second Windows machine to verify the `.exe` is portable

---

## Recommendation

**Plan B is the stronger choice if you want to ship to real Windows users.** The VM approach (Plan A) is convenient for quick testing but produces ARM64 binaries that won't run on typical Intel PCs. If budget allows, a cheap used Windows Intel laptop ($200-300) or a cloud VM ($0.10/hr when needed) gives you the most reliable Windows development and build environment.

The **GitHub Actions approach** (works with either plan) is the best long-term solution — zero local setup needed for builds after initial configuration.
