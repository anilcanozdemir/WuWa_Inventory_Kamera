"""
Debug harness for main-menu / ROI / OCR failures.

Usage (game running, ESC pause menu open, preferably exclusive fullscreen):
  .\\.venv\\Scripts\\python.exe tools\\debug_capture.py

Writes under debug_out/:
  - monitors.json          mss + window geometry
  - full_monitor.png       full capture of resolved monitor
  - roi_terminal.png       Terminal ROI used by MainMenuController
  - roi_terminal_bw.png    black/white preprocess of that ROI
  - ocr_report.txt         OCR strings + isMenu() result
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cv2
import mss

from game.foreground import WindowManager
from game.menu import MainMenuController
from scraping.utils.common import (
    convertToBlackWhite,
    definedText,
    imageToString,
    screenshot,
)

OUT = ROOT / "debug_out"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    runDir = OUT / stamp
    runDir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(runDir / "debug.log", encoding="utf-8"),
        ],
    )
    log = logging.getLogger("debug_capture")

    with mss.mss() as sct:
        monitors = [
            {"index": i, **mon} for i, mon in enumerate(sct.monitors)
        ]

    wm = WindowManager()
    if not wm.window:
        log.error(
            "Wuthering Waves window not found "
            "(title contains 'Wuthering Waves', process Client-Win64-Shipping.exe)."
        )
        (runDir / "monitors.json").write_text(
            json.dumps({"monitors": monitors, "window": None}, indent=2),
            encoding="utf-8",
        )
        return 1

    import win32gui

    try:
        result = wm.setForeground()
        log.info("setForeground: %s", result)
    except Exception as e:
        result = ("error", "Exception", str(e))
        log.warning("setForeground raised %s; continuing with capture", e)

    screenInfo = wm.getScreenInfo()
    pos = wm.getWindowPosition()
    size = wm.getWindowSize()
    dpi = wm.getDPI() if wm.window else 1.0
    fg = win32gui.GetForegroundWindow()
    gameHwnd = wm.window._hWnd if wm.window else None
    try:
        fgTitle = win32gui.GetWindowText(fg)
    except Exception:
        fgTitle = ""

    meta = {
        "monitors": monitors,
        "setForeground": list(result) if isinstance(result, tuple) else result,
        "foreground": {
            "hwnd": int(fg) if fg else None,
            "title": fgTitle,
            "is_game": bool(gameHwnd and fg == gameHwnd),
        },
        "window": {
            "title": wm.window.title if wm.window else None,
            "hwnd": int(gameHwnd) if gameHwnd else None,
            "position": {"x": pos.x, "y": pos.y} if pos else None,
            "size_raw": {"w": size[0], "h": size[1]} if size else None,
            "dpi_scale": dpi,
            "screenInfo": {
                "width": screenInfo.width,
                "height": screenInfo.height,
                "monitor": screenInfo.monitor,
                "terminal": {
                    "x": screenInfo.terminal.x,
                    "y": screenInfo.terminal.y,
                    "w": screenInfo.terminal.w,
                    "h": screenInfo.terminal.h,
                },
            },
        },
        "expected_terminal_label": definedText.get(
            "PrefabTextItem_1547656443_Text", "<missing definedText>"
        ),
        "note": (
            "mss captures the visible desktop. If foreground.is_game is false, "
            "full_monitor.png will show Cursor/browser instead of the game."
        ),
    }
    (runDir / "monitors.json").write_text(
        json.dumps(meta, indent=2), encoding="utf-8"
    )
    log.info("Wrote %s", runDir / "monitors.json")

    full = screenshot(monitor=screenInfo.monitor)
    cv2.imwrite(str(runDir / "full_monitor.png"), cv2.cvtColor(full, cv2.COLOR_RGB2BGR))

    term = screenshot(
        screenInfo.terminal.x,
        screenInfo.terminal.y,
        screenInfo.terminal.w,
        screenInfo.terminal.h,
        screenInfo.monitor,
    )
    cv2.imwrite(str(runDir / "roi_terminal.png"), cv2.cvtColor(term, cv2.COLOR_RGB2BGR))
    term_bw = convertToBlackWhite(term)
    cv2.imwrite(str(runDir / "roi_terminal_bw.png"), term_bw)

    ocr_raw = imageToString(term, "")
    ocr_bw = imageToString(term_bw, "")
    is_menu = MainMenuController().isMenu()

    report = "\n".join(
        [
            f"expected: {meta['expected_terminal_label']!r}",
            f"ocr_raw:  {ocr_raw!r}",
            f"ocr_bw:   {ocr_bw!r}",
            f"isMenu(): {is_menu}",
            f"monitor index used: {screenInfo.monitor}",
            f"logical size: {screenInfo.width}x{screenInfo.height}",
            f"dpi_scale: {dpi}",
        ]
    )
    (runDir / "ocr_report.txt").write_text(report + "\n", encoding="utf-8")
    print(report)
    print(f"\nArtifacts: {runDir}")
    return 0 if is_menu else 2


if __name__ == "__main__":
    raise SystemExit(main())
