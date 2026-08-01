"""Measure the real echo-grid behaviour: click targeting, wheel scrolling, sonata panel.

Run elevated with the game open on Inventory -> Echoes. Writes PNGs, a log and
report.json into debug_out/diag_<timestamp>/ so the numbers can be compared
against the values baked into game/gameROI.py.
"""

from __future__ import annotations

import json
import logging
import string
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.foreground import WindowManager
from scraping.utils import imageToString, screenshot, WindowsInputController

OUT = ROOT / "debug_out" / f"diag_{datetime.now():%Y%m%d_%H%M%S}"
OUT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[logging.FileHandler(OUT / "diag.log", encoding="utf-8"), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("diag")

NEUTRAL = (5, 5)  # park the cursor here so hover highlight never pollutes a capture
SETTLE = 0.9


def save(name: str, rgb: np.ndarray) -> None:
    cv2.imwrite(str(OUT / name), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


class Diag:
    def __init__(self) -> None:
        manager = WindowManager()
        status = manager.setForeground(minimizeScanner=False)
        log.info("focus=%s", status)
        time.sleep(0.6)
        self.screen = manager.getScreenInfo()
        self.ctl = WindowsInputController(self.screen.monitor)
        self.echoes = self.screen.echoes
        self.report: dict = {
            "resolution": [self.screen.width, self.screen.height],
            "monitor": self.screen.monitor,
            "config": {
                "start": [self.echoes.start.x, self.echoes.start.y, self.echoes.start.w, self.echoes.start.h],
                "offsets_page": [self.screen.offsets.page.x, self.screen.offsets.page.y],
                "scroll_page_y": self.screen.scroll.page.y,
                "scroll_sonata_y": self.screen.scroll.sonata.y,
                "mouseMovement": [self.echoes.mouseMovement.x, self.echoes.mouseMovement.y],
            },
        }
        log.info("config=%s", json.dumps(self.report["config"]))

    # ---- geometry helpers -------------------------------------------------
    def cellCenter(self, row: int, col: int) -> tuple[int, int]:
        s, off = self.echoes.start, self.screen.offsets.page
        return (
            int(s.x + col * (s.w + off.x) + s.w // 2),
            int(s.y + row * (s.h + off.y) + s.h // 2),
        )

    @property
    def gridRect(self) -> tuple[int, int, int, int]:
        s, off = self.echoes.start, self.screen.offsets.page
        return (int(s.x), int(s.y), int(6 * (s.w + off.x) - off.x), int(4 * (s.h + off.y) - off.y))

    def gridShot(self) -> np.ndarray:
        self.ctl.moveMouse(*NEUTRAL, 0.25)
        x, y, w, h = self.gridRect
        return screenshot(x, y, w, h, monitor=self.screen.monitor)

    def rowPitch(self, grid: np.ndarray) -> dict:
        """Row pitch from the horizontal gaps between cells (edge projection)."""
        gray = cv2.cvtColor(grid, cv2.COLOR_RGB2GRAY).astype(np.float32)
        profile = gray.mean(axis=1)

        centred = profile - profile.mean()
        corr = np.correlate(centred, centred, mode="full")[len(centred) - 1:]
        window = corr[200:360]
        autocorrPeak = int(np.argmax(window)) + 200

        # Cell gaps are the darkest horizontal bands; their spacing is the pitch.
        darkness = profile.max() - profile
        threshold = darkness.mean() + darkness.std()
        gaps, run = [], []
        for index, value in enumerate(darkness):
            if value > threshold:
                run.append(index)
            elif run:
                gaps.append(sum(run) / len(run))
                run = []
        if run:
            gaps.append(sum(run) / len(run))
        spacings = [round(b - a, 1) for a, b in zip(gaps, gaps[1:])]

        return {
            "autocorr_pitch_px": autocorrPeak,
            "gap_centres": [round(g, 1) for g in gaps],
            "gap_spacings": spacings,
            "config_row_pitch_px": int(self.echoes.start.h + self.screen.offsets.page.y),
        }

    @staticmethod
    def displacement(before: np.ndarray, after: np.ndarray, band: int = 150) -> dict:
        """Vertical shift of `after` vs `before`.

        The template is taken from the bottom of `before` so that even large
        upward content movement keeps it inside the search field.
        """
        top = before.shape[0] - band - 5
        template = cv2.cvtColor(before[top:top + band], cv2.COLOR_RGB2GRAY)
        field = cv2.cvtColor(after, cv2.COLOR_RGB2GRAY)
        res = cv2.matchTemplate(field, template, cv2.TM_CCOEFF_NORMED)
        _, score, _, loc = cv2.minMaxLoc(res)
        return {"dy_px": int(loc[1] - top), "confidence": round(float(score), 4), "max_measurable_px": -top}

    @staticmethod
    def sameImage(a: np.ndarray, b: np.ndarray) -> dict:
        diff = cv2.absdiff(a, b)
        return {"mean_abs_diff": round(float(diff.mean()), 3), "identical": bool(diff.mean() < 1.0)}

    def scrollAt(self, x: float, y: float, notches: float) -> None:
        self.ctl.moveMouse(x, y, 0.25)
        self.ctl.mouseScroll(notches, SETTLE)

    def scrollToTop(self) -> None:
        cx, cy = self.cellCenter(1, 2)
        for _ in range(3):
            self.scrollAt(cx, cy, 120)
        log.info("grid scrolled to top")

    # ---- experiments ------------------------------------------------------
    def checkGridVisible(self) -> bool:
        page = self.echoes.page
        image = screenshot(int(page.x), int(page.y), int(page.w), int(page.h), monitor=self.screen.monitor)
        save("00_page_roi.png", image)
        text = imageToString(image, allowedChars=string.digits + "/")
        log.info("page ROI OCR=%r", text)
        self.report["page_ocr"] = text
        if "/" not in text:
            log.error("Echo grid not detected. Open Inventory -> Echoes, then rerun.")
            return False
        self.report["echo_count"] = int(text.split("/")[0] or 0)
        return True

    def testClicks(self) -> None:
        """Does clicking each cell actually select a different echo?"""
        card = self.echoes.echoCard
        results = []
        for row, col in [(0, 0), (0, 1), (0, 2), (1, 0), (3, 5)]:
            x, y = self.cellCenter(row, col)
            self.ctl.leftClick(x, y)
            time.sleep(0.7)
            image = screenshot(int(card.x), int(card.y), int(card.w), int(card.h), monitor=self.screen.monitor)
            save(f"10_card_r{row}c{col}.png", image)
            lines = imageToString(image, "", bannedChars=" +").lower().split("\n")
            digest = int(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY).sum())
            log.info("click r%sc%s at (%s,%s) card=%s", row, col, x, y, lines)
            results.append({"row": row, "col": col, "click": [x, y], "card_lines": lines, "pixel_digest": digest})
        distinct = len({tuple(r["card_lines"]) for r in results})
        log.info("distinct echo cards across 5 clicks: %s/5", distinct)
        self.report["click_test"] = {"cells": results, "distinct_cards": distinct}

    def testGridScroll(self) -> None:
        """px moved per wheel notch, with the cursor over the grid."""
        self.scrollToTop()
        base = self.gridShot()
        save("20_grid_top.png", base)
        self.report["row_pitch"] = self.rowPitch(base)
        log.info("row pitch: %s", json.dumps(self.report["row_pitch"]))

        cx, cy = self.cellCenter(1, 2)
        measurements = []
        for notches in (1, 2, 4, 8, 16, 32):
            before = self.gridShot()
            self.scrollAt(cx, cy, -notches)
            after = self.gridShot()
            save(f"21_after_{notches}_notches.png", after)
            shift = self.displacement(before, after)
            perNotch = round(-shift["dy_px"] / notches, 3)
            log.info("scroll -%s notches -> dy=%s px (%s px/notch) conf=%s",
                     notches, shift["dy_px"], perNotch, shift["confidence"])
            measurements.append({"notches": notches, **shift, "px_per_notch": perNotch})
            self.scrollAt(cx, cy, notches)  # restore
            time.sleep(0.3)
        self.report["grid_scroll"] = measurements

        good = [m for m in measurements if m["confidence"] > 0.9 and m["dy_px"]]
        if good:
            perNotch = float(np.median([m["px_per_notch"] for m in good]))
            spacings = self.report["row_pitch"]["gap_spacings"]
            pitch = float(np.median(spacings)) if spacings else self.report["row_pitch"]["autocorr_pitch_px"]
            self.report["derived"] = {
                "px_per_notch": round(perNotch, 3),
                "row_pitch_px": round(pitch, 1),
                "notches_per_row": round(pitch / perNotch, 3) if perNotch else None,
                "notches_per_page_4rows": round(4 * pitch / perNotch, 3) if perNotch else None,
                "config_scroll_page_y": self.screen.scroll.page.y,
            }
            log.info("DERIVED %s", json.dumps(self.report["derived"]))

    def testScrollEquivalence(self) -> None:
        """Is one big wheel event the same as several small ones?

        echoScraper sends a single event per page. If the game clamps a single
        WM_MOUSEWHEEL, a page-sized value can never advance a full page.
        """
        cx, cy = self.cellCenter(1, 2)

        self.scrollToTop()
        top = self.gridShot()
        self.scrollAt(cx, cy, -64)
        single = self.gridShot()
        save("50_single_64.png", single)
        singleShift = self.displacement(top, single)

        self.scrollToTop()
        topAgain = self.gridShot()
        for _ in range(4):
            self.scrollAt(cx, cy, -16)
        stepped = self.gridShot()
        save("51_stepped_4x16.png", stepped)
        steppedShift = self.displacement(topAgain, stepped)

        equal = self.sameImage(single, stepped)
        log.info("single -64: dy=%s conf=%s | 4x-16: dy=%s conf=%s | same_image=%s",
                 singleShift["dy_px"], singleShift["confidence"],
                 steppedShift["dy_px"], steppedShift["confidence"], equal)
        self.report["scroll_equivalence"] = {
            "single_64": singleShift,
            "stepped_4x16": steppedShift,
            "images_match": equal,
            "top_captures_match": self.sameImage(top, topAgain),
        }

    def testScrollOverPanel(self) -> None:
        """Does the page scroll move the grid when the cursor sits on the detail panel?

        echoScraper() ends every scanned echo inside getSonata(), which leaves the
        cursor on the right-hand panel, and then scrolls the page from there.
        """
        self.scrollToTop()
        before = self.gridShot()
        mm = self.echoes.mouseMovement
        self.scrollAt(mm.x, mm.y, self.screen.scroll.page.y)
        after = self.gridShot()
        save("30_grid_after_panel_scroll.png", after)
        shift = self.displacement(before, after)
        log.info("page scroll from panel (%s,%s): grid dy=%s conf=%s", mm.x, mm.y, shift["dy_px"], shift["confidence"])

        cx, cy = self.cellCenter(1, 2)
        before2 = self.gridShot()
        self.scrollAt(cx, cy, self.screen.scroll.page.y)
        after2 = self.gridShot()
        save("31_grid_after_grid_scroll.png", after2)
        shift2 = self.displacement(before2, after2)
        log.info("page scroll from grid  (%s,%s): grid dy=%s conf=%s", cx, cy, shift2["dy_px"], shift2["confidence"])

        self.report["panel_vs_grid_scroll"] = {
            "cursor_on_panel": shift,
            "cursor_on_grid": shift2,
            "notches": self.screen.scroll.page.y,
        }

    def testSonata(self) -> None:
        """Which panel-scroll amount actually reveals the sonata name?"""
        self.scrollToTop()
        x, y = self.cellCenter(0, 0)
        self.ctl.leftClick(x, y)
        time.sleep(0.7)
        son, mm = self.echoes.sonata, self.echoes.mouseMovement
        results = []
        for notches in (70, self.screen.scroll.sonata.y):
            self.scrollAt(mm.x, mm.y, -notches)
            image = screenshot(int(son.x), int(son.y), int(son.w), int(son.h), monitor=self.screen.monitor)
            save(f"40_sonata_{notches}.png", image)
            text = imageToString(image, "", bannedChars=" ").lower()
            log.info("sonata scroll -%s -> OCR=%r", notches, text[:160])
            results.append({"notches": notches, "ocr": text[:400], "empty": not text.strip()})
            self.scrollAt(mm.x, mm.y, notches)
            time.sleep(0.3)
        self.report["sonata_test"] = results

    def run(self, scrollOnly: bool = False) -> int:
        full = screenshot(width=self.screen.width, height=self.screen.height, monitor=self.screen.monitor)
        save("01_full.png", full)
        if not self.checkGridVisible():
            self.finish()
            return 2
        if not scrollOnly:
            self.testClicks()
            self.testSonata()
            self.testScrollOverPanel()
        self.testGridScroll()
        self.testScrollEquivalence()
        self.finish()
        return 0

    def finish(self) -> None:
        (OUT / "report.json").write_text(json.dumps(self.report, indent=2), encoding="utf-8")
        (ROOT / "debug_out" / "_latest_diag.txt").write_text(str(OUT), encoding="utf-8")
        log.info("DONE -> %s", OUT)


if __name__ == "__main__":
    try:
        raise SystemExit(Diag().run(scrollOnly="--scroll-only" in sys.argv))
    except SystemExit:
        raise
    except Exception:
        log.exception("diagnostic crashed")
        raise SystemExit(1)
