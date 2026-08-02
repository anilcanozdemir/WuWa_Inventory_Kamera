"""OCR horizontal bands of the weapon detail panel to locate Lv text."""
from __future__ import annotations

import string
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.foreground import WindowManager
from properties.config import cfg
from scraping.utils import WindowsInputController, convertToBlackWhite, imageToString, screenshot

OUT = ROOT / "debug_out" / f"weapon_bands_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
OUT.mkdir(parents=True, exist_ok=True)


def hideConsole() -> None:
    try:
        import win32con
        import win32gui
        from ctypes import windll

        hwnd = windll.kernel32.GetConsoleWindow()
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    except Exception:
        pass


hideConsole()
manager = WindowManager()
manager.setForeground()
time.sleep(0.5)
screen = manager.getScreenInfo()
controller = WindowsInputController(screen.monitor)

# Assume inventory already open on weapons from previous probe; re-click first card.
controller.leftClick(
    int(screen.weapons.start.x + screen.weapons.start.w // 2),
    int(screen.weapons.start.y + screen.weapons.start.h // 2),
)
time.sleep(0.35)

full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
cv2.imwrite(str(OUT / "full.png"), cv2.cvtColor(full, cv2.COLOR_RGB2BGR))

# Right detail panel roughly x=1720..2500
lines = []
for y in range(150, 520, 20):
    box = (1720, y, 780, 40)
    crop = full[box[1]:box[1] + box[3], box[0]:box[0] + box[2]]
    raw = imageToString(crop, '')
    digits = imageToString(convertToBlackWhite(crop), '', allowedChars=string.digits + '/')
    if raw.strip() or digits.strip():
        lines.append(f"y={y}: full={raw!r} digits={digits!r}")
        cv2.imwrite(str(OUT / f"y{y}.png"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))

(OUT / "bands.txt").write_text("\n".join(lines), encoding="utf-8")
print(OUT, flush=True)
print("\n".join(lines), flush=True)
