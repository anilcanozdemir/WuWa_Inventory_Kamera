"""Elevated full inventory scan: characters + weapons + echoes.

Run with the game open:
  Start-Process .\\.venv\\Scripts\\python.exe -Verb RunAs `
    -ArgumentList 'tools\\scan_inventory.py' -WorkingDirectory (Get-Location)

Abort with F12. Writes debug_out/full_*/report.json.
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

ABORT_KEY_NAME = "F12"
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


print(f"Full inventory scan starting. Press {ABORT_KEY_NAME} to abort.", flush=True)
hideConsole()

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / "debug_out" / f"full_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[logging.FileHandler(OUT / "scan.log", encoding="utf-8")],
)
log = logging.getLogger("scan_inventory")


def watchAbortKey() -> None:
    import win32api

    # Ignore a still-held F12 from a previous abort so the new run is not killed instantly.
    while win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
        time.sleep(0.05)
    time.sleep(0.4)
    while True:
        if win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
            log.warning("Abort key %s pressed — stopping.", ABORT_KEY_NAME)
            logging.shutdown()
            os._exit(3)
        time.sleep(0.05)


def main() -> int:
    threading.Thread(target=watchAbortKey, daemon=True).start()

    import string

    from game.foreground import WindowManager
    from properties.config import cfg
    from scraping.charactersScraper import resonatorScraper
    from scraping.echoesScraper import echoScraper
    from scraping.utils import WindowsInputController, imageToString, savingScraped, screenshot
    from scraping.weaponsScraper import weaponScraper
    from game.menu import MainMenuController

    manager = WindowManager()
    status = manager.setForeground()
    log.info("focus=%s", status)
    if status[0] == "error":
        return 2

    time.sleep(1.0)
    screen = manager.getScreenInfo()
    controller = WindowsInputController(screen.monitor)
    menu = MainMenuController()
    started = time.time()

    # Inventory left open (bag counter visible) confuses Terminal/Overview OCR
    # and makes scrapers toggle the bag shut mid-flow.
    for attempt in range(3):
        page = screen.weapons.page
        probe = screenshot(int(page.x), int(page.y), int(page.w), int(page.h), monitor=screen.monitor)
        if "/" not in imageToString(probe, allowedChars=string.digits + "/"):
            break
        log.info("Inventory open — pressing ESC (attempt %s)", attempt + 1)
        controller.pressKey("esc", 0.7)
        time.sleep(0.6)

    characters = resonatorScraper(controller, screen)
    log.info("characters=%s", len(characters))

    # Resonator Overview is not Terminal — isMenu() is false — so leave it
    # explicitly before opening the backpack.
    for attempt in range(3):
        controller.pressKey("esc", 0.45)
        time.sleep(0.4)
        if menu.isMenu():
            if not menu.ensureGameplay(controller, maxEscapes=3):
                log.error("Could not leave Terminal before weapons")
                return 1
            break
        # Overview/inventory closed → gameplay (no terminal, no bag counter).
        page = screen.weapons.page
        probe = screenshot(int(page.x), int(page.y), int(page.w), int(page.h), monitor=screen.monitor)
        if "/" not in imageToString(probe, allowedChars=string.digits + "/"):
            break

    inventory, weapons, weaponExpected = weaponScraper(
        controller, screen.scrapers.weapons.x, screen.scrapers.weapons.y, screen,
    )
    log.info("weapons=%s expected=%s", len(weapons), weaponExpected)

    if menu.isMenu() and not menu.ensureGameplay(controller, maxEscapes=3):
        log.error("Could not leave Terminal before echoes")
        return 1

    echoes, echoExpected = echoScraper(
        controller, screen.scrapers.echoes.x, screen.scrapers.echoes.y, screen,
    )
    log.info("echoes=%s expected=%s", len(echoes), echoExpected)

    controller.pressKey("esc")
    elapsed = round(time.time() - started, 1)
    date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    savingScraped(
        {
            "characters_wuwainventorykamera.json": (characters, dict),
            "weapons_wuwainventorykamera.json": (weapons, list),
            "echoes_wuwainventorykamera.json": (echoes, list),
        },
        date,
    )

    shortfalls = []
    if weaponExpected and len(weapons) != weaponExpected:
        shortfalls.append(f"weapons {len(weapons)}/{weaponExpected}")
    if echoExpected and len(echoes) != echoExpected:
        shortfalls.append(f"echoes {len(echoes)}/{echoExpected}")

    report = {
        "elapsed_s": elapsed,
        "export": str(Path(cfg.get(cfg.exportFolder)) / date),
        "counts": {
            "characters": len(characters),
            "weapons": len(weapons),
            "echoes": len(echoes),
            "weaponExpected": weaponExpected,
            "echoExpected": echoExpected,
        },
        "shortfalls": shortfalls,
        # Pass when every OCR inventory counter we read matches scraped length.
        "ok": not shortfalls and (weaponExpected > 0 or echoExpected > 0 or len(characters) > 0),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (ROOT / "debug_out" / "_latest_full.txt").write_text(str(OUT), encoding="utf-8")
    log.info("DONE %s", json.dumps(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        log.exception("scan crashed")
        raise SystemExit(1)
