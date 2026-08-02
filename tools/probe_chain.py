"""Probe Resonance Chain: click each S node and OCR Activated.

Open Resonators → pick a char with known chain (e.g. Aalto S6 / Taoqi S1),
leave them on Overview (or already on Chain), then:

  tools\\START_PROBE_CHAIN.bat

Clicks left-rail Chain, then each chainPositions entry, OCRs Activated,
saves button crops under debug_out/chain_probe_*/.
F12 aborts.
"""
from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ABORT_VK = 0x7B
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / "debug_out" / f"chain_probe_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[
        logging.FileHandler(OUT / "probe.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("probe_chain")


def _watchAbort() -> None:
    import win32api

    while win32api.GetAsyncKeyState(ABORT_VK) & 0x8000:
        time.sleep(0.05)
    time.sleep(0.4)
    while True:
        if win32api.GetAsyncKeyState(ABORT_VK) & 0x8000:
            log.warning("F12 abort")
            logging.shutdown()
            os._exit(3)
        time.sleep(0.05)


def _saveCrop(screen, tag: str) -> None:
    import cv2
    from scraping.utils.common import screenshot

    base = screen.characters.skillButton
    chain = getattr(screen.characters, "chainButton", None)
    boxes = [("skillButton", base)]
    if chain is not None:
        boxes.append(("chainButton", chain))
    for name, box in boxes:
        x, y, w, h = int(box.x), int(box.y), int(box.w), int(box.h)
        img = screenshot(x, y, w, h, monitor=screen.monitor)
        path = OUT / f"{tag}_{name}.png"
        cv2.imwrite(str(path), cv2.cvtColor(img, cv2.COLOR_RGB2BGR) if img.ndim == 3 else img)


def main() -> int:
    print("CHAIN PROBE — select char with known S (Aalto/Taoqi). Overview OK. F12 aborts.", flush=True)
    threading.Thread(target=_watchAbort, daemon=True).start()

    from game.foreground import WindowManager
    from scraping.charactersScraper import (
        _leftRailClick,
        _ocrActivatedButton,
        isOnResonatorScreen,
    )
    from scraping.utils.mouse_keyboard import WindowsInputController

    wm = WindowManager()
    if wm.setForeground()[0] == "error":
        log.error("Game window not found")
        return 1
    time.sleep(0.5)
    screen = wm.getScreenInfo()
    controller = WindowsInputController(screen.monitor)

    if not isOnResonatorScreen(screen):
        log.error("Not on Resonator screen")
        return 1

    # section 4 = Chain (Overview=0 … Chain=4)
    _leftRailClick(controller, screen, 4)
    time.sleep(0.5)

    results = []
    chain = 0
    for i, pos in enumerate(screen.characters.chainPositions):
        controller.leftClick(pos.x, pos.y, 0.25)
        time.sleep(0.45)
        is_on, button = _ocrActivatedButton(screen)
        tag = f"s{i + 1}"
        _saveCrop(screen, tag)
        row = {
            "node": i + 1,
            "xy": [int(pos.x), int(pos.y)],
            "activated": bool(is_on),
            "button": button,
        }
        results.append(row)
        log.info("S%s @(%s,%s) activated=%s button=%r", i + 1, pos.x, pos.y, is_on, button)
        print(f"  S{i + 1}: activated={is_on}  OCR={button!r}", flush=True)

        # Close node detail so the next Sequence icon is clickable.
        controller.pressKey("esc", 0.2)
        time.sleep(0.35)
        if not isOnResonatorScreen(screen):
            log.error("Left Resonator after Esc on S%s", i + 1)
            break

        if not is_on:
            break
        chain += 1

    report = {
        "chain_count": chain,
        "nodes": results,
        "positions": [[int(p.x), int(p.y)] for p in screen.characters.chainPositions],
        "chainClick": [
            int(screen.characters.chainClick.x),
            int(screen.characters.chainClick.y),
        ],
        "out": str(OUT),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nchain={chain}  → {OUT}", flush=True)
    log.info("DONE chain=%s", chain)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
