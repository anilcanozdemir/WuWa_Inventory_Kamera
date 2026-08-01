"""
Live debug: focus WuWa, open Resonators from Terminal tile, OCR roster slots.

Prefer elevated (same as release exe):
  Start-Process .\\.venv\\Scripts\\python.exe -Verb RunAs -ArgumentList 'tools\\live_debug_characters.py' -WorkingDirectory (Get-Location)
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.foreground import WindowManager
from game.menu import MainMenuController
from scraping.charactersScraper import (
    isOnResonatorOverview,
    parseLevelPair,
    scrapeResonator,
)
from scraping.utils.common import convertToBlackWhite, imageToString, screenshot
from scraping.utils.mouse_keyboard import WindowsInputController
from properties.config import cfg

OUT = ROOT / "debug_out" / f"live_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def save_rgb(path: Path, rgb) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def crop(rgb, box):
    return rgb[box.y : box.y + box.h, box.x : box.x + box.w]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(OUT / "live.log", encoding="utf-8"),
        ],
    )
    log = logging.getLogger("live_debug")

    wm = WindowManager()
    if not wm.window:
        log.error("Game window not found")
        return 1

    focus = wm.setForeground(minimizeScanner=True)
    log.info("focus=%s admin_hint=run elevated if clicks fail", focus)
    time.sleep(0.5)

    screen = wm.getScreenInfo()
    controller = WindowsInputController(screen.monitor)
    menu = MainMenuController()

    meta = {
        "size": [screen.width, screen.height],
        "monitor": screen.monitor,
        "name_box": vars(screen.characters.resonatorName),
        "level_box": vars(screen.characters.resonatorLevel),
        "terminalResonators": vars(getattr(screen.characters, "terminalResonators", None) or type("C", (), {"x": None, "y": None, "w": 0, "h": 0})()),
        "right": vars(screen.characters.rightSide),
        "left": vars(screen.characters.leftSide),
    }
    (OUT / "meta.json").write_text(json.dumps(meta, indent=2, default=str), encoding="utf-8")

    full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    save_rgb(OUT / "00_before.png", full)

    if menu.isMenu():
        tile = screen.characters.terminalResonators
        log.info("Terminal open — clicking Resonators (%s,%s)", tile.x, tile.y)
        controller.leftClick(tile.x, tile.y, 0.4)
        time.sleep(1.3)
    elif not isOnResonatorOverview(screen):
        key = cfg.get(cfg.resonatorKeybind)
        log.info("Pressing %r", key)
        controller.pressKey(key, 2, False)
        time.sleep(1.0)

    full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    save_rgb(OUT / "01_after_open.png", full)
    log.info(
        "state terminal=%s overview=%s",
        menu.isMenu(),
        isOnResonatorOverview(screen),
    )

    if menu.isMenu():
        log.error("Still on Terminal — input not reaching game (need Admin?)")
        (OUT / "report.json").write_text(
            json.dumps({"error": "stuck_on_terminal", "meta": meta}, indent=2),
            encoding="utf-8",
        )
        return 2

    if isOnResonatorOverview(screen):
        controller.leftClick(screen.characters.leftSide.x, screen.characters.leftSide.y, 0.5)
        time.sleep(0.4)

    full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    save_rgb(OUT / "02_overview.png", full)

    name_img = crop(full, screen.characters.resonatorName)
    level_img = crop(full, screen.characters.resonatorLevel)
    save_rgb(OUT / "roi_name.png", name_img)
    save_rgb(OUT / "roi_level.png", level_img)

    report = {
        "overview": isOnResonatorOverview(screen),
        "name_raw": imageToString(name_img, ""),
        "name_bw": imageToString(convertToBlackWhite(name_img), ""),
        "level_raw": imageToString(level_img, ""),
        "level_bw": imageToString(convertToBlackWhite(level_img), ""),
    }
    report["level_parsed"] = parseLevelPair(report["level_raw"] or report["level_bw"])
    log.info("ROI report: %s", report)

    characters: dict = {}
    cache: dict = {}
    results = []
    x = screen.characters.rightSide.x
    y0 = screen.characters.rightSide.y
    step = screen.characters.offsets.rightSide.y

    for i in range(7):
        controller.leftClick(x, y0 + step * i, 0.7)
        time.sleep(0.4)
        frame = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
        save_rgb(OUT / f"slot_{i}.png", frame)
        rid, stop = scrapeResonator(frame, screen, characters, cache)
        entry = {
            "slot": i,
            "id": rid,
            "stop": stop,
            "level": characters.get(rid, {}).get("level") if rid else None,
            "ascension": characters.get(rid, {}).get("ascension") if rid else None,
        }
        results.append(entry)
        log.info("slot %s -> %s", i, entry)
        if stop:
            break

    (OUT / "report.json").write_text(
        json.dumps(
            {
                "roi": report,
                "slots": results,
                "characters": {str(k): dict(v) for k, v in characters.items()},
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    log.info("Artifacts: %s scraped=%s", OUT, len(characters))
    return 0 if characters else 3


if __name__ == "__main__":
    raise SystemExit(main())
