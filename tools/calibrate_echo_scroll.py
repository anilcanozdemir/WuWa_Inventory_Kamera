"""Short elevated calibration for echo-grid scroll + read (2-3 pages).

Does NOT run a full inventory scan. It:
  1. scrolls the list to the top
  2. reads the first cell of each visible row (name OCR only)
  3. advances one page at a time with GridPageScroller
  4. saves before/after grid screenshots + a diff for each step
  5. checks row-start names against tools/expected_echoes.json when present

Run via tools/START_ECHO_CALIBRATE.bat (must be elevated — the game ignores
input from a normal process). Press F12 to abort.
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
DEFAULT_PAGES = 3
FIXTURE = ROOT / "tools" / "expected_echoes.json"


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


print(f"Echo scroll calibrate. Press {ABORT_KEY_NAME} to abort.", flush=True)
hideConsole()

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / "debug_out" / f"calib_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[logging.FileHandler(OUT / "calib.log", encoding="utf-8")],
)
log = logging.getLogger("calibrate")

from difflib import get_close_matches as getMatches

from game.foreground import WindowManager
from scraping.echoesScraper import COLS, ROWS, getEchoPages
from scraping.utils import WindowsInputController, echoesID, imageToString, screenshot
from scraping.utils.gridScroll import GridPageScroller, savePersistedRate


def watchAbortKey() -> None:
    import win32api

    while True:
        if win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
            log.warning("Abort key %s pressed", ABORT_KEY_NAME)
            logging.shutdown()
            os._exit(3)
        time.sleep(0.05)


def saveRgb(name: str, rgb: np.ndarray) -> str:
    path = OUT / name
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))
    return path.name


def saveDiff(name: str, before: np.ndarray, after: np.ndarray) -> dict:
    diff = cv2.absdiff(before, after)
    mean = float(diff.mean())
    heat = cv2.applyColorMap(
        cv2.normalize(cv2.cvtColor(diff, cv2.COLOR_RGB2GRAY), None, 0, 255, cv2.NORM_MINMAX),
        cv2.COLORMAP_INFERNO,
    )
    side = np.hstack([
        cv2.cvtColor(before, cv2.COLOR_RGB2BGR),
        cv2.cvtColor(after, cv2.COLOR_RGB2BGR),
        heat,
    ])
    cv2.imwrite(str(OUT / name), side)
    return {"mean_absdiff": round(mean, 2), "side_by_side": name}


def bare(name: str) -> str:
    return name.replace(":", "").replace("-", "").lower()


def matchesWant(want: str, got: str | None) -> bool:
    if not got:
        return False
    w, g = bare(want), bare(got)
    return g.startswith(w) or w in g or g in w


def loadFixture() -> dict:
    try:
        return json.loads(FIXTURE.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def cellCenter(screen, row: int, col: int) -> tuple[int, int]:
    s, off = screen.echoes.start, screen.offsets.page
    return (
        int(s.x + col * (s.w + off.x) + s.w // 2),
        int(s.y + row * (s.h + off.y) + s.h // 2),
    )


def readCellName(controller, screen, row: int, col: int = 0) -> str:
    """Click one cell and OCR only the detail-card name (no sonata/stats)."""
    x, y = cellCenter(screen, row, col)
    controller.leftClick(x, y, 0.25)
    time.sleep(0.15)
    image = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    card = screen.echoes.echoCard
    crop = image[card.y:card.y + card.h, card.x:card.x + card.w]
    lines = imageToString(crop, "", bannedChars=" +").lower().split("\n")
    name = (lines[0] if lines else "").strip()
    if name and name not in echoesID:
        matched = getMatches(name, echoesID, 1, 0.8)
        if matched:
            name = matched[0]
    return name if name in echoesID else name


def readPageRowStarts(controller, screen) -> list[str]:
    return [readCellName(controller, screen, row, 0) for row in range(ROWS)]


def annotateGrid(rgb: np.ndarray, screen, page: int) -> np.ndarray:
    """Label each left-column cell with global echo index (#1, #7, ...)."""
    out = rgb.copy()
    s, off = screen.echoes.start, screen.offsets.page
    for row in range(ROWS):
        index = page * ROWS * COLS + row * COLS + 1  # 1-based inventory index
        cx = 8
        cy = int(row * (s.h + off.y) + 28)
        label = f"#{index}"
        cv2.putText(out, label, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(out, label, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0, 255, 255), 2, cv2.LINE_AA)
    return out


def saveCellCrops(full: np.ndarray, screen, page: int, names: list[str]) -> list[str]:
    """Crop the left-column cards from a full-screen shot for human ID."""
    paths = []
    s, off = screen.echoes.start, screen.offsets.page
    for row in range(ROWS):
        x = int(s.x)
        y = int(s.y + row * (s.h + off.y))
        w, h = int(s.w), int(s.h)
        crop = full[y:y + h, x:x + w]
        index = page * ROWS * COLS + row * COLS + 1
        name = f"{page:02d}_cell_r{row}_i{index}_{bare(names[row]) or 'unknown'}.png"
        saveRgb(name, crop)
        paths.append(name)
    return paths


def buildAskUser(report: dict) -> list[dict]:
    """Questions for the human when OCR/fixture disagree or scroll looks off."""
    asks = []
    for check in report["row_checks"]:
        index = check.get("echo_index") or (
            (check["page"] - 1) * ROWS * COLS + (check["row"] - 1) * COLS + 1
        )
        if not check["ok"]:
            asks.append({
                "id": f"row_p{check['page']}_r{check['row']}",
                "echo_index": index,
                "question": (
                    f"Liste basi 1 iken {index}. echo (sayfa {check['page']}, "
                    f"gorunen satir {check['row']}, sol sutun) ne? "
                    f"OCR '{check['got'] or '?'}' dedi"
                    + (f", fixture '{check['expected']}' bekliyordu." if check["expected"] else ".")
                ),
                "ocr": check["got"],
                "fixture": check["expected"],
            })
    for step in report["steps"]:
        scroll = step.get("scroll")
        if not scroll:
            continue
        moved, target = scroll.get("moved_px"), scroll.get("target_px")
        if moved is None or (target and abs(moved - target) > 40):
            asks.append({
                "id": f"scroll_p{step['page']}",
                "question": (
                    f"Sayfa {step['page']}→{step['page'] + 1} kaydirmadan sonra "
                    f"sol ustteki echo ne? (tam 4 satir mi indi? "
                    f"olcum: moved={moved} target={target})"
                ),
                "screenshot": scroll.get("side_by_side"),
            })
    return asks


def main(pages: int = DEFAULT_PAGES) -> int:
    threading.Thread(target=watchAbortKey, daemon=True).start()

    manager = WindowManager()
    status = manager.setForeground()
    log.info("focus=%s", status)
    if status[0] == "error":
        return 2

    time.sleep(0.8)
    screen = manager.getScreenInfo()
    controller = WindowsInputController(screen.monitor)
    fixture = loadFixture()
    rowStarts = list(fixture.get("rowStarts") or [])

    echoCount, inventoryPages = getEchoPages(screen)
    log.info(
        "screen=%sx%s echoes=%s pages=%s calib_pages=%s expected_px_per_notch≈%.2f",
        screen.width, screen.height, echoCount, inventoryPages, pages,
        (screen.echoes.start.h + screen.offsets.page.y) * ROWS / abs(screen.scroll.page.y),
    )

    scroller = GridPageScroller(controller, screen, screen.echoes, ROWS, COLS, "echoes")
    scroller.scrollToTop(inventoryPages)

    report: dict = {
        "out": str(OUT),
        "echo_count": echoCount,
        "inventory_pages": inventoryPages,
        "calib_pages": pages,
        "expected_px_per_notch": round(scroller.expectedPxPerNotch, 2),
        "config_notches": scroller.configNotches,
        "steps": [],
        "rate_samples": [],
        "locked_px_per_notch": None,
        "row_checks": [],
        "ask_user": [],
        "ok": True,
    }

    topGrid = scroller._capture()
    saveRgb("00_top_grid.png", topGrid)
    saveRgb("00_top_grid_labeled.png", annotateGrid(topGrid, screen, 0))
    scroller.rowPitch = scroller._measureRowPitch(topGrid)
    report["row_pitch"] = scroller.rowPitch
    report["expected_px_per_notch"] = round(scroller.expectedPxPerNotch, 2)

    for page in range(pages):
        step: dict = {"page": page + 1}
        names = readPageRowStarts(controller, screen)
        step["row_starts"] = names

        full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
        grid = scroller._capture()
        saveRgb(f"{page:02d}_page_grid.png", grid)
        saveRgb(f"{page:02d}_page_grid_labeled.png", annotateGrid(grid, screen, page))
        step["cell_crops"] = saveCellCrops(full, screen, page, names)

        for row, got in enumerate(names):
            wantIdx = page * ROWS + row
            want = rowStarts[wantIdx] if wantIdx < len(rowStarts) else None
            ok = matchesWant(want, got) if want else bool(got) and got in echoesID
            check = {
                "page": page + 1,
                "row": row + 1,
                "echo_index": page * ROWS * COLS + row * COLS + 1,
                "fixture_index": wantIdx,
                "expected": want,
                "got": got,
                "ok": bool(ok),
            }
            report["row_checks"].append(check)
            if want and not ok:
                report["ok"] = False
            log.info(
                "page %s row %s (#%s): expected=%s got=%s ok=%s",
                page + 1, row + 1, check["echo_index"], want, got, ok,
            )

        if page >= pages - 1:
            report["steps"].append(step)
            break

        before = scroller._capture()
        saveRgb(f"{page:02d}_before_scroll.png", before)
        rateBefore = scroller.pxPerNotch
        samplesBefore = list(scroller._rateSamples)

        scrolled = scroller.scrollPage()
        after = scroller._capture()
        saveRgb(f"{page:02d}_after_scroll.png", after)
        saveRgb(f"{page:02d}_after_scroll_labeled.png", annotateGrid(after, screen, page + 1))
        diff = saveDiff(f"{page:02d}_scroll_diff.png", before, after)
        moved, score = GridPageScroller._displacement(before, after)

        step["scrolled"] = scrolled
        step["scroll"] = {
            **diff,
            "moved_px": None if moved is None else round(moved, 1),
            "match_score": round(score, 3),
            "target_px": round(scroller.rows * (scroller.rowPitch or 0), 1),
            "px_per_notch_before": rateBefore,
            "px_per_notch_after": scroller.pxPerNotch,
            "new_samples": scroller._rateSamples[len(samplesBefore):],
            "carry_px": round(scroller.carryPx, 1),
        }
        report["steps"].append(step)
        report["rate_samples"] = list(scroller._rateSamples)
        report["locked_px_per_notch"] = scroller.pxPerNotch

        target = scroller.rows * (scroller.rowPitch or 0)
        if moved is not None and target and abs(moved - target) > (scroller.rowPitch or 0) * 0.4:
            report["ok"] = False
            log.warning(
                "page %s scroll off: moved %.0f of %.0f",
                page + 1, moved, target,
            )
        if not scrolled:
            report["ok"] = False
            log.warning("scrollPage returned False on page %s", page + 1)
            break

        log.info(
            "page %s→%s scroll moved=%s target=%.0f rate=%s carry=%.0f",
            page + 1, page + 2, moved, target, scroller.pxPerNotch, scroller.carryPx,
        )

    matched = sum(1 for c in report["row_checks"] if c["ok"])
    report["row_match"] = f"{matched}/{len(report['row_checks'])}"
    report["locked_px_per_notch"] = scroller.pxPerNotch
    report["rate_samples"] = list(scroller._rateSamples)
    report["ask_user"] = buildAskUser(report)
    if scroller.pxPerNotch is not None:
        savePersistedRate("echoes", scroller.pxPerNotch, scroller.rowPitch)

    askPath = OUT / "ASK_USER.json"
    askPath.write_text(json.dumps(report["ask_user"], indent=2, ensure_ascii=False), encoding="utf-8")
    lines = ["Kalibrasyon sorulari (oyunda bakip cevapla):", ""]
    if not report["ask_user"]:
        lines.append("Soru yok — OCR ve kaydirma fixture ile uyustu.")
    for q in report["ask_user"]:
        lines.append(f"- [#{q.get('echo_index', '?')}] {q['question']}")
    (OUT / "ASK_USER.txt").write_text("\n".join(lines), encoding="utf-8")

    (OUT / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    (ROOT / "debug_out" / "_latest_calib.txt").write_text(str(OUT), encoding="utf-8")
    log.info("DONE %s", json.dumps(report, ensure_ascii=False))
    print(json.dumps({
        "ok": report["ok"],
        "row_match": report["row_match"],
        "locked_px_per_notch": report["locked_px_per_notch"],
        "rate_samples": report["rate_samples"],
        "ask_user_count": len(report["ask_user"]),
        "out": str(OUT),
    }, indent=2), flush=True)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    pages = DEFAULT_PAGES
    if len(sys.argv) > 1:
        try:
            pages = max(1, int(sys.argv[1]))
        except ValueError:
            pass
    try:
        raise SystemExit(main(pages))
    except SystemExit:
        raise
    except Exception:
        log.exception("calibrate crashed")
        raise SystemExit(1)
