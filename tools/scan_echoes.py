"""Run only the echo scraper and report what it produced.

Used to verify the grid page scrolling end to end. Run elevated with the game
open; the console is minimised immediately so it cannot cover the capture area.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from collections import Counter
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# F12 rather than ENTER/ESC: both of those are live keys in game and would abort
# a healthy scan by accident.
ABORT_KEY_NAME = "F12"
ABORT_KEY_VK = 0x7B


def hideConsole() -> None:
    """A console window on top of the grid corrupts every screenshot."""
    try:
        import win32con
        import win32gui
        from ctypes import windll

        hwnd = windll.kernel32.GetConsoleWindow()
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    except Exception:
        pass


print(f"Echo scan starting. Press {ABORT_KEY_NAME} at any time to abort.", flush=True)
hideConsole()

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / "debug_out" / f"scan_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[logging.FileHandler(OUT / "scan.log", encoding="utf-8")],
)
log = logging.getLogger("scan_echoes")

import string

from game.foreground import WindowManager
from properties.config import cfg
from scraping.echoesScraper import COLS, echoScraper
from scraping.utils import WindowsInputController, echoesID, imageToString, savingScraped, screenshot


def watchAbortKey() -> None:
    """Hard-exit when the abort key is pressed.

    The scrape loop owns the main thread and is driving the mouse, so polling
    the key from a daemon thread and calling os._exit is the only escape hatch
    that always works — a normal exception could be swallowed mid-click.
    """
    import win32api

    # Ignore a still-held F12 from a previous abort so the new run is not killed instantly.
    while win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
        time.sleep(0.05)
    time.sleep(0.4)
    while True:
        if win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
            log.warning("Abort key %s pressed — stopping the scan.", ABORT_KEY_NAME)
            logging.shutdown()
            os._exit(3)
        time.sleep(0.05)


def inventoryIsOpen(screen) -> bool:
    page = screen.echoes.page
    image = screenshot(int(page.x), int(page.y), int(page.w), int(page.h), monitor=screen.monitor)
    return "/" in imageToString(image, allowedChars=string.digits + "/")


def closeInventory(controller: WindowsInputController, screen) -> None:
    """echoScraper toggles the inventory hotkey, so it must start from gameplay."""
    for attempt in range(3):
        if not inventoryIsOpen(screen):
            return
        log.info("Inventory still open — pressing ESC (attempt %s)", attempt + 1)
        controller.pressKey("esc", 0.7)
        time.sleep(0.6)
    log.warning("Could not close the inventory; the scan may open the wrong screen.")


# Optional test fixture. The scanner itself never assumes an inventory size or
# any particular echo: the count comes from the in-game counter. This file only
# lets a run be checked against a snapshot of one specific inventory, so it has
# to be updated (or deleted) whenever more echoes are farmed.
FIXTURE = ROOT / "tools" / "expected_echoes.json"


def loadFixture() -> dict:
    try:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def checkFixture(names: list[str], fixture: dict) -> dict:
    """Compare a scan against the optional fixture; empty when none is present."""
    if not fixture:
        return {}

    def matches(want: str, got: str | None) -> bool:
        if not got:
            return False
        bare = got.replace(":", "").replace("-", "")
        return want in bare or bare.startswith(want)

    result: dict = {}

    # First echo of each row: a dropped cell shifts everything after it, so the
    # first mismatch marks where the scan started losing cards.
    rowStarts = fixture.get("rowStarts") or []
    if rowStarts:
        checks = []
        for row, want in enumerate(rowStarts):
            index = row * COLS
            got = names[index] if index < len(names) else None
            checks.append({"row": row + 1, "index": index, "expected": want,
                           "got": got, "ok": matches(want, got)})
        result["row_start_check"] = checks
        result["row_start_matches"] = f"{sum(1 for c in checks if c['ok'])}/{len(checks)}"
        result["first_shifted_row"] = next((c["row"] for c in checks if not c["ok"]), None)

    expectedTotal = fixture.get("total")
    if expectedTotal:
        result["expected_total"] = expectedTotal
        result["missing_vs_fixture"] = expectedTotal - len(names)

    tail = fixture.get("tail") or []
    if tail:
        result["tail_targets"] = {
            target: [i for i, n in enumerate(names) if n == target][-3:]
            for target in tail
        }

    return result


def summarise(echoes: list) -> dict:
    reverse = {str(v): k for k, v in echoesID.items()}
    names = [reverse.get(next(iter(e)), "?" + next(iter(e))) for e in echoes]

    signatures = [json.dumps(e, sort_keys=True) for e in echoes]
    runs, index = [], 0
    while index < len(signatures):
        end = index
        while end + 1 < len(signatures) and signatures[end + 1] == signatures[index]:
            end += 1
        if end > index:
            runs.append({"start": index, "length": end - index + 1, "name": names[index]})
        index = end + 1

    report = {
        "total": len(echoes),
        "distinct_names": len(set(names)),
        "first_12": names[:12],
        "last_12": names[-12:],
        "longest_identical_runs": sorted(runs, key=lambda r: -r["length"])[:5],
        "sonata_empty": sum(1 for e in echoes if not e[next(iter(e))]["sonata"]),
        "level_zero": sum(1 for e in echoes if not e[next(iter(e))]["level"]),
        "rarity_histogram": dict(Counter(e[next(iter(e))]["rarity"] for e in echoes)),
    }
    report.update(checkFixture(names, loadFixture()))
    return report


def main() -> int:
    threading.Thread(target=watchAbortKey, daemon=True).start()
    log.info("Abort key: %s", ABORT_KEY_NAME)

    manager = WindowManager()
    status = manager.setForeground()
    log.info("focus=%s", status)
    if status[0] == "error":
        return 2

    time.sleep(1.0)
    screen = manager.getScreenInfo()
    controller = WindowsInputController(screen.monitor)
    log.info(
        "screen=%sx%s monitor=%s scroll.page.y=%s minRarity=%s minLevel=%s",
        screen.width, screen.height, screen.monitor, screen.scroll.page.y,
        cfg.get(cfg.echoMinRarity), cfg.get(cfg.echoMinLevel),
    )

    closeInventory(controller, screen)

    started = time.time()
    echoes, echoCount = echoScraper(controller, screen.scrapers.echoes.x, screen.scrapers.echoes.y, screen)
    elapsed = round(time.time() - started, 1)

    date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    savingScraped({"echoes_wuwainventorykamera.json": (echoes, list)}, date)

    report = {
        "elapsed_s": elapsed,
        "export": str(Path(cfg.get(cfg.exportFolder)) / date),
        "echo_count_ocr": echoCount,
        **summarise(echoes),
    }
    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (ROOT / "debug_out" / "_latest_scan.txt").write_text(str(OUT), encoding="utf-8")
    log.info("DONE %s", json.dumps(report))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        log.exception("scan crashed")
        raise SystemExit(1)
