"""Targeted dead-page debug — ONLY the pages you care about, no full scan.

Default targets: pages 4, 12, 13 (the ones that died in recent full runs).

Flow:
  1. scroll to top
  2. optional 1-cell panel-OCR repro on page 1 (screenshots)
  3. burst-scroll to each target page WITHOUT reading cells in between
  4. on a target page: click all 24 cells; dump screenshots on every miss
     + before/after panel reset

Usage (elevated):
  tools\\START_DEAD_PAGE_DIAG.bat
  tools\\START_DEAD_PAGE_DIAG.bat 4 12 13
  tools\\START_DEAD_PAGE_DIAG.bat 4

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

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ABORT_KEY_NAME = "F12"
ABORT_KEY_VK = 0x7B
DEFAULT_TARGETS = (4, 12, 13)


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


print(f"Dead-page TARGET diag. Press {ABORT_KEY_NAME} to abort.", flush=True)
hideConsole()

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / "debug_out" / f"dead_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[logging.FileHandler(OUT / "dead.log", encoding="utf-8")],
)
log = logging.getLogger("dead_page")

from game.foreground import WindowManager
from scraping.echoesScraper import (
    CELL_MISS,
    CELL_OK,
    CELL_STOP,
    COLS,
    ROWS,
    _matchSonataIcon,
    _ocrSonataByScrolling,
    _resetDetailPanel,
    getEchoPages,
    processGridEcho,
)
from scraping.utils import WindowsInputController, imageToString, screenshot
from scraping.utils.gridScroll import GridPageScroller


def watchAbort() -> None:
    import win32api

    while True:
        if win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
            log.warning("Abort %s", ABORT_KEY_NAME)
            logging.shutdown()
            os._exit(3)
        time.sleep(0.05)


def saveRgb(name: str, rgb: np.ndarray) -> str:
    cv2.imwrite(str(OUT / name), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return name


def crop(image: np.ndarray, roi) -> np.ndarray:
    return image[int(roi.y):int(roi.y + roi.h), int(roi.x):int(roi.x + roi.w)]


def dumpState(tag: str, screen, image: np.ndarray, extra: dict | None = None) -> dict:
    card = crop(image, screen.echoes.echoCard)
    info: dict = {"tag": tag, **(extra or {})}
    info["full"] = saveRgb(f"{tag}_full.png", image)
    info["card"] = saveRgb(f"{tag}_card.png", card)
    info["ocr_lines"] = imageToString(card, "", bannedChars=" +").lower().split("\n")
    iconRoi = getattr(screen.echoes, "sonataIcon", None)
    if iconRoi and iconRoi.w and iconRoi.h:
        icon = crop(image, iconRoi)
        info["icon"] = saveRgb(f"{tag}_sonata_icon.png", icon)
        name, score = _matchSonataIcon(icon)
        info["sonata_best"] = name
        info["sonata_score"] = round(score, 3)
    if hasattr(screen.echoes, "sonata"):
        info["sonata_panel"] = saveRgb(f"{tag}_sonata_panel.png", crop(image, screen.echoes.sonata))
    log.info(
        "dump %s ocr=%s sonata=%s/%.3f",
        tag, info["ocr_lines"][:3], info.get("sonata_best"), info.get("sonata_score") or 0,
    )
    return info


def cellCenter(screen, row: int, col: int) -> tuple[int, int]:
    s, off = screen.echoes.start, screen.offsets.page
    return (
        int(s.x + col * (s.w + off.x) + s.w // 2),
        int(s.y + row * (s.h + off.y) + s.h // 2),
    )


def scrollToPage(scroller: GridPageScroller, current: int, target: int) -> int:
    """Burst-scroll from 1-based `current` page to `target` without reading cells."""
    while current < target:
        if not scroller.scrollPage():
            log.warning("scroll stopped at page %s (wanted %s)", current, target)
            return current
        current += 1
        log.info("fast-scrolled to page %s", current)
    return current


def reproPanelFallback(controller, screen) -> dict:
    x, y = cellCenter(screen, 0, 0)
    controller.leftClick(x, y, 0.25)
    time.sleep(0.15)
    before = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    beforeInfo = dumpState("repro_before", screen, before)

    sonata = _ocrSonataByScrolling(controller, screen)
    after = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    afterInfo = dumpState("repro_after", screen, after, {"sonata_ocr": sonata})

    lines = afterInfo["ocr_lines"]
    nameOk = bool(lines and lines[0] and len(lines[0]) > 2)
    result = {
        "sonata_ocr": sonata,
        "before_ocr": beforeInfo["ocr_lines"][:4],
        "after_ocr": lines[:4],
        "panel_undo_ok": nameOk and beforeInfo["ocr_lines"][:1] == lines[:1],
    }
    log.info("repro: %s", result)
    return result


def scanTargetPage(controller, screen, scroller, page: int, echoes: list, cache: dict) -> dict:
    """Read all 24 cells on the current page; dump on misses only."""
    saveRgb(f"p{page:02d}_grid.png", scroller._capture())
    ok = miss = 0
    missStreak = 0
    dumps: list[dict] = []

    for row in range(ROWS):
        for col in range(COLS):
            x, y = cellCenter(screen, row, col)
            controller.leftClick(x, y, 0.12)
            image = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
            status = processGridEcho(controller, screen, echoes, image, cache)
            if status == CELL_MISS:
                time.sleep(0.12)
                image = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
                status = processGridEcho(controller, screen, echoes, image, cache)

            if status == CELL_STOP:
                return {"page": page, "ok": ok, "miss": miss, "stopped": True, "dumps": dumps}
            if status == CELL_OK:
                ok += 1
                missStreak = 0
                continue

            miss += 1
            missStreak += 1
            tag = f"p{page:02d}_r{row}c{col}_m{missStreak}"
            dumps.append(dumpState(tag, screen, image, {
                "page": page, "row": row, "col": col, "miss_streak": missStreak,
            }))

            if missStreak >= 3:
                before = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
                dumps.append(dumpState(f"{tag}_before_reset", screen, before))
                _resetDetailPanel(controller, screen)
                time.sleep(0.2)
                after = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
                dumps.append(dumpState(f"{tag}_after_reset", screen, after))
                if processGridEcho(controller, screen, echoes, after, cache) == CELL_OK:
                    ok += 1
                    miss -= 1
                    missStreak = 0
                    log.info("reset recovered p%s r%s c%s", page, row, col)

    dead = miss >= 20 or ok == 0
    if dead:
        saveRgb(f"p{page:02d}_DEAD_grid.png", scroller._capture())
    return {"page": page, "ok": ok, "miss": miss, "dead": dead, "dumps": len(dumps), "dump_tags": [d["tag"] for d in dumps]}


def parseTargets(argv: list[str]) -> list[int]:
    if not argv:
        return list(DEFAULT_TARGETS)
    out: list[int] = []
    for arg in argv:
        for part in arg.replace(",", " ").split():
            out.append(max(1, int(part)))
    return sorted(set(out))


def main(targets: list[int]) -> int:
    threading.Thread(target=watchAbort, daemon=True).start()

    manager = WindowManager()
    status = manager.setForeground()
    log.info("focus=%s targets=%s", status, targets)
    if status[0] == "error":
        return 2

    time.sleep(0.6)
    screen = manager.getScreenInfo()
    controller = WindowsInputController(screen.monitor)
    echoCount, inventoryPages = getEchoPages(screen)
    targets = [p for p in targets if p <= inventoryPages]
    if not targets:
        log.error("no valid target pages")
        return 1

    scroller = GridPageScroller(controller, screen, screen.echoes, ROWS, COLS, "echoes")
    scroller.scrollToTop(inventoryPages)

    report: dict = {
        "out": str(OUT),
        "echo_count": echoCount,
        "targets": targets,
        "repro": {},
        "pages": [],
        "dead_pages": [],
    }

    # One-cell repro on page 1 only (does not scan the page).
    report["repro"] = reproPanelFallback(controller, screen)
    _resetDetailPanel(controller, screen)

    echoes: list = []
    cache: dict = {}
    current = 1
    for target in targets:
        current = scrollToPage(scroller, current, target)
        if current != target:
            report["pages"].append({"page": target, "error": f"only reached {current}"})
            break
        summary = scanTargetPage(controller, screen, scroller, target, echoes, cache)
        report["pages"].append({k: v for k, v in summary.items() if k != "dump_tags"} | {
            "dump_tags": summary.get("dump_tags", []),
        })
        if summary.get("dead"):
            report["dead_pages"].append(target)
        log.info("target page %s → ok=%s miss=%s dead=%s", target, summary["ok"], summary["miss"], summary.get("dead"))

    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "debug_out" / "_latest_dead.txt").write_text(str(OUT), encoding="utf-8")
    print(json.dumps({
        "out": str(OUT),
        "targets": targets,
        "dead_pages": report["dead_pages"],
        "repro_panel_undo_ok": report["repro"].get("panel_undo_ok"),
        "pages": [{k: p.get(k) for k in ("page", "ok", "miss", "dead")} for p in report["pages"]],
    }, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main(parseTargets(sys.argv[1:])))
    except SystemExit:
        raise
    except Exception:
        log.exception("dead-page diag crashed")
        raise SystemExit(1)
