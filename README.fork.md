# WuWa Inventory Kamera (fork)

Fork of [Psycho-Marcus/WuWa_Inventory_Kamera](https://github.com/Psycho-Marcus/WuWa_Inventory_Kamera)
for fixing scan failures on current Wuthering Waves builds.

Remote: https://github.com/anilcanozdemir/WuWa_Inventory_Kamera

## Why this fork

Upstream often fails before any character/echo scan starts:

1. **Wrong monitor** — `DISPLAY1` Win32 names were treated as `mss` indices, so OCR
   read the other monitor (browser text like YouTube/GitHub).
2. **Brittle Terminal OCR** — main-menu gate compared the raw OCR string with
   `difflib.get_close_matches` without the same normalization as `definedText.json`,
   so newlines / spaces made `isMenu()` false even when Terminal was visible.
3. **Silent OCR errors** — `imageToString` swallowed exceptions and returned `''`.

## Dev setup

```powershell
cd C:\Users\white\Projects\wuwa-inventory-kamera
python -m venv .venv
.\.venv\Scripts\pip.exe install -r requirements.txt
.\.venv\Scripts\python.exe tools\bootstrap_data.py
```

## Debug a live scan failure

1. Launch Wuthering Waves (prefer **exclusive fullscreen**, 1920×1080 or 2560×1440).
2. Press **ESC** so the pause / Terminal menu is visible.
3. **Leave the game on top** — do not keep Cursor/browser covering it. `mss` captures
   pixels on screen; if Cursor is focused, OCR reads the IDE (this fork’s first
   live capture did exactly that).
4. Run from an elevated PowerShell if the game is elevated:

```powershell
.\.venv\Scripts\python.exe tools\debug_capture.py
```

Inspect `debug_out/<timestamp>/`:

- `monitors.json` → `foreground.is_game` must be `true`
- `full_monitor.png` — must be the game, not Cursor/another monitor
- `roi_terminal.png` — should contain the word Terminal
- `ocr_report.txt` — `isMenu(): True` means the gate is fixed

## Run the app from source

```powershell
.\.venv\Scripts\python.exe main.py
```

Start with only **Characters** enabled for the first verification pass.
