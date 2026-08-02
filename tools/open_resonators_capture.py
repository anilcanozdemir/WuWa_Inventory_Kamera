"""From Terminal (or gameplay), open Resonators and dump Overview ROIs."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.foreground import WindowManager
from game.menu import MainMenuController
from properties.config import cfg
from scraping.charactersScraper import (
    ensureResonatorOverview,
    isOnResonatorOverview,
    isOnResonatorScreen,
    parseLevelPair,
    scrapeResonator,
)
from scraping.utils.common import convertToBlackWhite, imageToString, screenshot
from scraping.utils.mouse_keyboard import WindowsInputController

OUT = ROOT / "debug_out" / f"open_chars_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def save_rgb(path: Path, rgb) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def crop(rgb, box):
    return rgb[box.y : box.y + box.h, box.x : box.x + box.w]


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wm = WindowManager()
    if wm.setForeground()[0] == "error":
        return 1
    time.sleep(0.5)
    screen = wm.getScreenInfo()
    controller = WindowsInputController(screen.monitor)
    menu = MainMenuController()

    full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    save_rgb(OUT / "00_before.png", full)

    state = {
        "terminal": menu.isMenu(),
        "resonator_screen": isOnResonatorScreen(screen),
        "overview": isOnResonatorOverview(screen),
    }
    print("before", state)

    if state["resonator_screen"]:
        ensureResonatorOverview(controller, screen)
    elif state["terminal"]:
        tile = screen.characters.terminalResonators
        print(f"click Resonators ({tile.x},{tile.y})")
        controller.leftClick(tile.x, tile.y, 0.35)
        time.sleep(1.4)
    else:
        key = cfg.get(cfg.resonatorKeybind)
        print(f"press {key!r}")
        controller.pressKey(key, 2, False)
        time.sleep(1.0)

    full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    save_rgb(OUT / "01_after_open.png", full)
    state2 = {
        "terminal": menu.isMenu(),
        "resonator_screen": isOnResonatorScreen(screen),
        "overview": isOnResonatorOverview(screen),
    }
    print("after open", state2)

    if state2["resonator_screen"] and not state2["overview"]:
        ensureResonatorOverview(controller, screen)
        full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
        save_rgb(OUT / "02_overview_click.png", full)

    # Always click Overview tab once more (same as scraper).
    controller.leftClick(screen.characters.leftSide.x, screen.characters.leftSide.y, 0.5)
    time.sleep(0.5)
    full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    save_rgb(OUT / "03_overview.png", full)

    name_img = crop(full, screen.characters.resonatorName)
    level_img = crop(full, screen.characters.resonatorLevel)
    save_rgb(OUT / "roi_name.png", name_img)
    save_rgb(OUT / "roi_level.png", level_img)

    # Broader search for name/level text
    grid = []
    for y in range(80, 450, 25):
        for x, w, h in [(200, 450, 45), (240, 520, 55), (280, 480, 50)]:
            c = full[y : y + h, x : x + w]
            raw = imageToString(c, "")
            if sum(ch.isalpha() for ch in raw) >= 3 or any(ch.isdigit() for ch in raw):
                grid.append({"x": x, "y": y, "w": w, "h": h, "raw": raw})

    characters: dict = {}
    cache: dict = {}
    slots = []
    x = screen.characters.rightSide.x
    y0 = screen.characters.rightSide.y
    step = screen.characters.offsets.rightSide.y
    for i in range(7):
        controller.leftClick(x, y0 + step * i, 0.65)
        time.sleep(0.35)
        frame = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
        save_rgb(OUT / f"slot_{i}.png", frame)
        rid, stop = scrapeResonator(frame, screen, characters, cache)
        slots.append({"slot": i, "id": rid, "stop": stop, "data": dict(characters.get(rid) or {})})
        print("slot", i, rid, stop)
        if stop and i > 0:
            break

    report = {
        "before": state,
        "after_open": state2,
        "name_raw": imageToString(name_img, ""),
        "name_bw": imageToString(convertToBlackWhite(name_img), ""),
        "level_raw": imageToString(level_img, ""),
        "level_bw": imageToString(convertToBlackWhite(level_img), ""),
        "level_parsed": parseLevelPair(
            imageToString(level_img, "") or imageToString(convertToBlackWhite(level_img), "")
        ),
        "grid_hits": grid[:40],
        "slots": slots,
        "characters": {str(k): dict(v) for k, v in characters.items()},
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (ROOT / "debug_out" / "_latest_open_chars.txt").write_text(str(OUT), encoding="utf-8")
    print(OUT)
    print(json.dumps({k: report[k] for k in ("name_raw", "name_bw", "level_raw", "level_bw", "level_parsed", "slots")}, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
