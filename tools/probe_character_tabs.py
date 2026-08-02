"""Discover resonator left-rail tabs and dump Weapon/Forte/Echo/Chain screenshots.

Run elevated with Resonator Overview open:
  Start-Process .\\.venv\\Scripts\\python.exe -Verb RunAs `
    -ArgumentList 'tools\\probe_character_tabs.py' -WorkingDirectory (Get-Location)
"""
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
from scraping.charactersScraper import (
    clickResonatorTab,
    discoverResonatorTabs,
    ensureResonatorOverview,
    isOnResonatorOverview,
    scrapeWeapon,
)
from scraping.utils.common import imageToString, screenshot
from scraping.utils.mouse_keyboard import WindowsInputController

OUT = ROOT / "debug_out" / f"char_tabs_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def save(path: Path, rgb) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wm = WindowManager()
    if wm.setForeground()[0] == "error":
        print("Game window not found")
        return 1
    time.sleep(0.4)
    screen = wm.getScreenInfo()
    controller = WindowsInputController(screen.monitor)

    if not isOnResonatorOverview(screen) and not ensureResonatorOverview(controller, screen):
        print("Not on Resonator Overview — open it first")
        return 1

    report: dict = {"size": [screen.width, screen.height], "tabs": {}, "weapons": {}}
    tabMap = discoverResonatorTabs(controller, screen)
    report["tabs"] = {k: list(v) for k, v in tabMap.items()}
    print("tabMap", tabMap)

    for tab in ("overview", "weapon", "echo", "forte", "chain"):
        ok = clickResonatorTab(controller, screen, tab, tabMap)
        time.sleep(0.4)
        img = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
        save(OUT / f"{tab}.png", img)
        report.setdefault("verify", {})[tab] = ok
        print(f"tab {tab} ok={ok}")

    # Weapon OCR smoke on currently selected resonator (Luuk if at top).
    clickResonatorTab(controller, screen, "weapon", tabMap)
    time.sleep(0.4)
    img = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    chars: dict = {}
    from collections import defaultdict
    chars = defaultdict(lambda: defaultdict(int, {
        "weapon": defaultdict(int, {"id": 0, "level": 1, "ascension": 0, "rank": 0}),
    }))
    scrapeWeapon(img, screen, chars, "probe", {})
    report["weapons"] = dict(chars.get("probe", {}).get("weapon", {}))
    print("weapon probe", report["weapons"])

    ensureResonatorOverview(controller, screen)
    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
