"""Open weapons inventory (from Terminal if needed), click first card, probe level OCR."""
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
from game.gameROI import Coordinates
from game.menu import MainMenuController
from properties.config import cfg
from scraping.utils import WindowsInputController, convertToBlackWhite, imageToString, screenshot

OUT = ROOT / "debug_out" / f"weapon_roi_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
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
print(manager.setForeground(), flush=True)
time.sleep(0.8)
screen = manager.getScreenInfo()
controller = WindowsInputController(screen.monitor)
menu = MainMenuController()

# Leave Terminal / close overlays without bouncing back into Terminal.
if menu.isMenu():
    menu.ensureGameplay(controller, maxEscapes=4)
    time.sleep(0.5)

controller.pressKey(cfg.get(cfg.inventoryKeybind), 2, False)
time.sleep(0.8)
controller.leftClick(screen.scrapers.weapons.x, screen.scrapers.weapons.y)
time.sleep(0.6)
cx = int(screen.weapons.start.x + screen.weapons.start.w // 2)
cy = int(screen.weapons.start.y + screen.weapons.start.h // 2)
controller.leftClick(cx, cy)
time.sleep(0.4)

full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
cv2.imwrite(str(OUT / "full.png"), cv2.cvtColor(full, cv2.COLOR_RGB2BGR))

candidates = {
    "name": screen.weapons.name,
    "level_cfg": screen.weapons.level,
    "level_old": Coordinates(2213, 313, 240, 60),
    "header_tall": Coordinates(
        screen.weapons.name.x,
        screen.weapons.name.y,
        screen.weapons.name.w,
        screen.weapons.name.h + 90,
    ),
}

lines = []
for key, box in candidates.items():
    crop = full[int(box.y):int(box.y + box.h), int(box.x):int(box.x + box.w)]
    if crop.size == 0:
        lines.append(f"{key}: EMPTY_CROP {box}")
        continue
    cv2.imwrite(str(OUT / f"{key}.png"), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
    bw = convertToBlackWhite(crop)
    cv2.imwrite(str(OUT / f"{key}_bw.png"), bw)
    lines.append(
        f"{key}: digits={imageToString(crop, '', allowedChars=string.digits + '/')!r} "
        f"bw={imageToString(bw, '', allowedChars=string.digits + '/')!r} "
        f"full={imageToString(crop, '')!r}"
    )

(OUT / "ocr.txt").write_text("\n".join(lines), encoding="utf-8")
print(OUT, flush=True)
print("\n".join(lines), flush=True)
