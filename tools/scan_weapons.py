"""Elevated weapons-only scan for debugging the backpack grid loop."""
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

ABORT_KEY_VK = 0x7B


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


print("Weapons scan starting. F12 aborts.", flush=True)
hideConsole()
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / "debug_out" / f"weapons_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[logging.FileHandler(OUT / "scan.log", encoding="utf-8")],
)
log = logging.getLogger("scan_weapons")


def watchAbort() -> None:
    import win32api

    while win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
        time.sleep(0.05)
    time.sleep(0.4)
    while True:
        if win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
            log.warning("F12 abort")
            logging.shutdown()
            os._exit(3)
        time.sleep(0.05)


def main() -> int:
    threading.Thread(target=watchAbort, daemon=True).start()
    import string

    from game.foreground import WindowManager
    from game.menu import MainMenuController
    from properties.config import cfg
    from scraping.utils import WindowsInputController, imageToString, savingScraped, screenshot
    from scraping.weaponsScraper import weaponScraper

    manager = WindowManager()
    if manager.setForeground()[0] == "error":
        return 2
    time.sleep(0.8)
    screen = manager.getScreenInfo()
    controller = WindowsInputController(screen.monitor)
    menu = MainMenuController()

    if menu.isMenu():
        menu.ensureGameplay(controller, maxEscapes=4)
    for _ in range(2):
        page = screen.weapons.page
        probe = screenshot(int(page.x), int(page.y), int(page.w), int(page.h), monitor=screen.monitor)
        # If bag already open leave it; else open via scraper.
        if "/" in imageToString(probe, allowedChars=string.digits + "/"):
            controller.pressKey("esc", 0.5)
            time.sleep(0.5)

    started = time.time()
    inventory, weapons, keptReads = weaponScraper(
        controller, screen.scrapers.weapons.x, screen.scrapers.weapons.y, screen,
    )
    elapsed = round(time.time() - started, 1)
    date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    savingScraped(
        {
            "weapons_wuwainventorykamera.json": (weapons, list),
            "items_wuwainventorykamera.json": (inventory, dict),
        },
        date,
    )

    from scraping.weaponsScraper import ENERGY_CORE_KEYS, _energyCoreNames
    from scraping.utils import itemsID

    cores = _energyCoreNames(inventory)
    reads = len(weapons) + len(inventory)
    report = {
        "elapsed_s": elapsed,
        "weapons": len(weapons),
        "items": len(inventory),
        "energy_cores": len(cores),
        "energy_core_names": cores,
        "reads": reads,
        # keptReads is scraper-reported target (full bag OCR, or weapons+items after rarity floor).
        "expected_reads": keptReads,
        "ok": bool(keptReads) and reads == keptReads,
        "export": str(Path(cfg.get(cfg.exportFolder)) / date),
        "min_rarity": cfg.get(cfg.weaponsMinRarity),
        "min_level": cfg.get(cfg.weaponsMinLevel),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    log.info("DONE %s", report)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        log.exception("crashed")
        raise SystemExit(1)
