import json
import logging
import time
from pathlib import Path

import cv2
import numpy as np

from game.screenInfo import ScreenInfo
from scraping.utils.common import screenshot
from scraping.utils.mouse_keyboard import WindowsInputController

logger = logging.getLogger('GridScroll')

ROWS, COLS = 4, 6

# Persisted after a successful short calibrate / first good lock so full scans
# can burst immediately instead of redoing slow one-row calibration.
CALIB_PATH = Path(__file__).resolve().parents[2] / 'data' / 'echo_scroll_calib.json'

# The first page is advanced one row at a time: overlapping content is what
# makes the wheel rate measurable. Once that rate is known every later page is
# one single burst, which is ~4x fewer scrolls, captures and settle waits.
CALIBRATION_STEP_ROWS = 1
# A single bad displacement (scan log: 236px / 10.6 notches = 22.17) used to
# lock the rate immediately and then every page burst overshot. Require two
# clean samples near the config expectation before trusting the learned rate.
MIN_CALIBRATION_SAMPLES = 2
LEARN_MAX_TARGET_ERROR = 0.20   # fraction of a row pitch
LEARN_MAX_RATE_ERROR = 0.25    # fraction of config-expected px/notch

TOLERANCE_PX = 4
MAX_CORRECTIONS = 1
# Settles used to be 1.0s which made a 33-page scan crawl. With a locked rate
# the grid is stable well under half a second after a chunked page burst.
SETTLE = 0.35
CHUNK_SETTLE = 0.04
TOP_SETTLE = 0.45
# A single WM_MOUSEWHEEL of ~31 notches only moved ~15 on the live 1440p
# client, so large page scrolls must be broken into small events. 16 is still
# below that clamp and halves the chunk count vs the old 8.
MAX_NOTCHES_PER_EVENT = 16
# Top-reset only overshoots upward (game clamps); full page-sized chunks are fine.
TOP_RESET_CHUNK = 32
TEMPLATE_BAND = 200
MIN_MATCH_SCORE = 0.75
MIN_TEMPLATE_STD = 12
# Absolute sanity bounds. The tighter check against config expectation is what
# rejects the 22 px/notch false learn; this range only catches nonsense.
PX_PER_NOTCH_RANGE = (8.0, 60.0)
# Leftover pixels are carried into the next step instead of being dropped: a
# step that is consistently a few px short would otherwise accumulate into a
# whole row over a page and push clicks into the gaps between cards.
MAX_CARRY_ROWS = 0.5


def loadPersistedRate(name: str = 'echoes') -> float | None:
    try:
        data = json.loads(CALIB_PATH.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return None
    entry = data.get(name) or data.get('px_per_notch')
    if isinstance(entry, dict):
        rate = entry.get('px_per_notch')
    else:
        rate = entry
    try:
        rate = float(rate)
    except (TypeError, ValueError):
        return None
    if PX_PER_NOTCH_RANGE[0] <= rate <= PX_PER_NOTCH_RANGE[1]:
        return rate
    return None


def savePersistedRate(name: str, pxPerNotch: float, rowPitch: float | None = None) -> None:
    CALIB_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(CALIB_PATH.read_text(encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        data = {}
    data[name] = {
        'px_per_notch': round(float(pxPerNotch), 4),
        'row_pitch': None if rowPitch is None else round(float(rowPitch), 2),
        'updated': time.strftime('%Y-%m-%dT%H:%M:%S'),
    }
    CALIB_PATH.write_text(json.dumps(data, indent=2), encoding='utf-8')
    logger.info('%s: persisted wheel rate %.2f px/notch → %s', name, pxPerNotch, CALIB_PATH)


class GridPageScroller:
    """Advances an inventory grid by whole rows, verifying the wheel took effect.

    The grid ignores the wheel unless the cursor is over it, and the notch
    counts in gameROI.py are per-resolution guesses, so the achieved pixel
    displacement is measured after every step and nudged until it matches a
    whole number of rows. The pixels-per-notch ratio is learned from the first
    step, which keeps the scan correct on machines the constants were never
    calibrated against.
    """

    def __init__(
        self,
        controller: WindowsInputController,
        screenInfo: ScreenInfo,
        grid,
        rows: int = ROWS,
        cols: int = COLS,
        name: str = 'grid',
    ):
        self.controller = controller
        self.screenInfo = screenInfo
        self.grid = grid
        self.rows = rows
        self.cols = cols
        self.name = name
        self.pxPerNotch: float | None = None
        self.rowPitch: float | None = None
        self.carryPx = 0.0
        self._rateSamples: list[float] = []
        persisted = loadPersistedRate(name)
        source = name
        # Weapons/echoes share backpack geometry, but a stale echoes rate makes
        # weapon page bursts no-op (~7px of 1100). Let weapons calibrate fresh.
        if persisted is not None:
            self.pxPerNotch = persisted
            logger.info(
                "%s: using %s wheel rate %.2f px/notch",
                name, source, persisted,
            )

    @property
    def rect(self) -> tuple[int, int, int, int]:
        start, offsets = self.grid.start, self.screenInfo.offsets.page
        return (
            int(start.x),
            int(start.y),
            int(self.cols * (start.w + offsets.x) - offsets.x),
            int(self.rows * (start.h + offsets.y) - offsets.y),
        )

    @property
    def configRowPitch(self) -> float:
        return float(self.grid.start.h + self.screenInfo.offsets.page.y)

    @property
    def configNotches(self) -> float:
        return abs(float(self.screenInfo.scroll.page.y))

    @property
    def expectedPxPerNotch(self) -> float:
        """Config-derived rate: page notches move `rows` row pitches."""
        pitch = self.rowPitch or self.configRowPitch
        return pitch * self.rows / self.configNotches

    def _capture(self) -> np.ndarray:
        x, y, w, h = self.rect
        return screenshot(x, y, w, h, monitor=self.screenInfo.monitor)

    def _parkOnGrid(self) -> None:
        x, y, w, h = self.rect
        # Prefer the right edge (scrollbar / gutter). Parking on a card center and
        # then wheeling often scrolls the detail panel instead of the list, and
        # identical weapon icons also make displacement matching unreliable there.
        self.controller.moveMouse(x + max(w - 12, w // 2), y + h // 2, 0.05)

    def _focusGrid(self) -> None:
        """Click the gutter so the wheel targets the list, not the detail panel."""
        x, y, w, h = self.rect
        self.controller.leftClick(x + max(w - 12, w // 2), y + h // 2)
        time.sleep(0.08)
        self._parkOnGrid()

    def _wheel(self, downNotches: float, maxChunk: float | None = None) -> None:
        """Scroll down by `downNotches`, chunked so the game cannot clamp the event."""
        self._parkOnGrid()
        chunkLimit = float(maxChunk if maxChunk is not None else MAX_NOTCHES_PER_EVENT)
        remaining = float(downNotches)
        while abs(remaining) > 1e-6:
            step = max(-chunkLimit, min(chunkLimit, remaining))
            wait = SETTLE if abs(remaining - step) <= 1e-6 else CHUNK_SETTLE
            self.controller.mouseScroll(-step, wait)
            remaining -= step

    def scrollToTop(self, pageCount: int) -> None:
        """Force the grid to its first row before scanning.

        The counter is visible at every scroll position, so callers can derive
        the maximum possible distance from the dynamic item/page count. Sending
        one page more than that distance safely overshoots: the game clamps the
        grid at the top.
        """
        pages = max(1, int(pageCount))
        upNotches = self.configNotches * (pages + 1)
        logger.info(
            "%s: returning to first row (up %.1f notches for %s pages)",
            self.name, upNotches, pages,
        )
        # Keep any persisted rate across the reset — only clear the in-scan carry.
        self._wheel(-upNotches, maxChunk=TOP_RESET_CHUNK)
        self.carryPx = 0.0
        self._parkOnGrid()
        time.sleep(TOP_SETTLE)

    def _measureRowPitch(self, grid: np.ndarray) -> float:
        """Cell pitch from the vertical periodicity of the grid image."""
        config = self.configRowPitch
        profile = cv2.cvtColor(grid, cv2.COLOR_RGB2GRAY).astype(np.float32).mean(axis=1)
        profile -= profile.mean()
        corr = np.correlate(profile, profile, mode='full')[len(profile) - 1:]
        if corr[0] <= 0:
            return config

        corr = corr / corr[0]
        low, high = int(config * 0.75), int(config * 1.3)
        window = corr[low:high]
        if window.size < 3:
            return config

        peak = int(np.argmax(window))
        score = float(window[peak])
        pitch = low + peak

        if score < 0.15 or peak in (0, window.size - 1):
            logger.warning(
                "%s: row pitch not measurable (best %spx, score %.2f) — using config %.0f",
                self.name, pitch, score, config,
            )
            return config

        # A low-confidence peak far from the configured card pitch (weapons log:
        # 219px vs 283 config @ score 0.27) makes every page burst under-scroll
        # and the same cards get clicked again.
        if abs(pitch - config) / config > 0.12:
            logger.warning(
                "%s: row pitch %spx too far from config %.0f (score %.2f) — using config",
                self.name, pitch, config, score,
            )
            return config

        logger.info(
            "%s: row pitch %spx (config %.0f, score %.2f)",
            self.name, pitch, config, score,
        )
        return float(pitch)

    @staticmethod
    def _displacement(before: np.ndarray, after: np.ndarray) -> tuple[float | None, float]:
        """Pixels the content moved up, or None when no band matched confidently.

        Bands are tried from the bottom of the grid upwards: the grid scrolls
        content upwards, so the lowest band is the one most likely to still be
        on screen afterwards. Bands that already scrolled off would otherwise
        match some other row of near-identical echo cards.
        """
        beforeGray = cv2.cvtColor(before, cv2.COLOR_RGB2GRAY)
        afterGray = cv2.cvtColor(after, cv2.COLOR_RGB2GRAY)

        bestScore = 0.0
        for top in range(beforeGray.shape[0] - TEMPLATE_BAND, -1, -60):
            template = beforeGray[top:top + TEMPLATE_BAND]
            if float(template.std()) < MIN_TEMPLATE_STD:
                continue
            result = cv2.matchTemplate(afterGray, template, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            bestScore = max(bestScore, float(score))
            if score >= MIN_MATCH_SCORE:
                return float(top - location[1]), float(score)

        return None, bestScore

    @staticmethod
    def _changed(before: np.ndarray, after: np.ndarray) -> bool:
        """True when the grid image actually changed (handles repeating echo cards)."""
        return float(cv2.absdiff(before, after).mean()) >= 1.5

    @staticmethod
    def _changeMagnitude(before: np.ndarray, after: np.ndarray) -> float:
        """Mean absdiff — selection glow is ~1–3; a real page jump is usually ≫6."""
        return float(cv2.absdiff(before, after).mean())

    def _rowStrips(self, grid: np.ndarray) -> list[np.ndarray]:
        """Downscaled mid-row strips used to measure row shift."""
        start, offsets = self.grid.start, self.screenInfo.offsets.page
        cellH = int(start.h)
        gapY = int(offsets.y)
        gray = cv2.cvtColor(grid, cv2.COLOR_RGB2GRAY)
        strips: list[np.ndarray] = []
        for row in range(self.rows):
            y0 = row * (cellH + gapY)
            y1 = min(gray.shape[0], y0 + cellH)
            strip = gray[y0 + cellH // 4:max(y0 + cellH // 4 + 1, y1 - cellH // 4), :]
            if strip.size == 0:
                strips.append(np.zeros((16, 64), dtype=np.uint8))
                continue
            strips.append(cv2.resize(strip, (64, 16), interpolation=cv2.INTER_AREA))
        return strips

    def _cellStrip(self, grid: np.ndarray, row: int, col: int) -> np.ndarray:
        """Downscaled interior of one card — ignores selection glow on the border."""
        start, offsets = self.grid.start, self.screenInfo.offsets.page
        cellW, cellH = int(start.w), int(start.h)
        gapX, gapY = int(offsets.x), int(offsets.y)
        gray = cv2.cvtColor(grid, cv2.COLOR_RGB2GRAY)
        x0 = col * (cellW + gapX)
        y0 = row * (cellH + gapY)
        x1 = min(gray.shape[1], x0 + cellW)
        y1 = min(gray.shape[0], y0 + cellH)
        # Inset ~18% so the gold selection rim does not flip the match.
        insetX = max(2, int(cellW * 0.18))
        insetY = max(2, int(cellH * 0.18))
        cell = gray[y0 + insetY:max(y0 + insetY + 1, y1 - insetY), x0 + insetX:max(x0 + insetX + 1, x1 - insetX)]
        if cell.size == 0:
            return np.zeros((24, 24), dtype=np.uint8)
        return cv2.resize(cell, (24, 24), interpolation=cv2.INTER_AREA)

    def _rowsMatch(self, a: np.ndarray, b: np.ndarray, rowA: int, rowB: int) -> bool:
        """True when most cards in rowA of `a` match rowB of `b`."""
        matches = sum(
            1 for col in range(self.cols)
            if self._stripsMatch(self._cellStrip(a, rowA, col), self._cellStrip(b, rowB, col), maxMeanDiff=12.0)
        )
        return matches >= max(4, self.cols - 1)

    @staticmethod
    def _stripsMatch(a: np.ndarray, b: np.ndarray, maxMeanDiff: float = 8.0) -> bool:
        return float(cv2.absdiff(a, b).mean()) <= maxMeanDiff

    def _overlapRows(self, before: np.ndarray, after: np.ndarray) -> int:
        """How many leading rows of `after` still match the trailing rows of `before`."""
        for overlap in range(self.rows, 0, -1):
            if all(
                self._rowsMatch(before, after, self.rows - overlap + i, i)
                for i in range(overlap)
            ):
                return overlap
        return 0

    def _rowsShifted(self, before: np.ndarray, after: np.ndarray) -> int:
        """How many rows the grid advanced. 0 = same page; -1 = indeterminate."""
        # Prefer cell-row matching over whole-strip hashes (selection glow).
        if self._rowsMatch(before, after, 0, 0) and self._rowsMatch(before, after, 1, 1):
            return 0

        bestShift = 0
        bestMatches = -1
        for shift in range(0, self.rows):
            overlap = self.rows - shift
            matches = sum(
                1 for row in range(overlap)
                if self._rowsMatch(before, after, row + shift, row)
            )
            if matches > bestMatches or (matches == bestMatches and shift > bestShift):
                bestShift, bestMatches = shift, matches

        if bestShift > 0 and bestMatches >= max(1, self.rows - bestShift - 1):
            return bestShift

        # No overlapping rows matched → either full page of new cards, or noise.
        # Only claim a full page when the top row clearly changed AND there is
        # no trailing-row overlap (caller also checks overlap separately).
        if not self._rowsMatch(before, after, 0, 0) and self._overlapRows(before, after) == 0:
            return self.rows
        return 0

    def _pageAdvanced(self, before: np.ndarray, after: np.ndarray) -> bool:
        """True when a full page of rows moved with no trailing-row overlap."""
        shifted = self._rowsShifted(before, after)
        overlap = self._overlapRows(before, after)
        logger.debug(
            "%s: row-shift estimate %s/%s overlap=%s",
            self.name, shifted, self.rows, overlap,
        )
        if shifted < 0:
            return False
        # A 3/4 shift leaves the last row glued to the next page (extra Hollow).
        return shifted >= self.rows and overlap == 0

    def _finishPageScroll(self, before: np.ndarray, after: np.ndarray) -> bool:
        """Nudge remaining rows when a page burst left 1–N rows of overlap."""
        for _ in range(self.rows):
            overlap = self._overlapRows(before, after)
            # Cell-level catch for the common 1-row glue (last Hollow/Marcato row).
            if overlap <= 0 and self._rowsMatch(before, after, self.rows - 1, 0):
                overlap = 1
            if overlap <= 0:
                shifted = self._rowsShifted(before, after)
                logger.debug(
                    "%s: finish page scroll shifted=%s overlap=0",
                    self.name, shifted,
                )
                return shifted >= self.rows
            logger.warning(
                "%s: page scroll left %s-row overlap — nudging %s row(s)",
                self.name, overlap, overlap,
            )
            self._focusGrid()
            if not self._scrollRows(float(overlap)):
                return False
            after = self._capture()
        return self._overlapRows(before, after) == 0 and not self._rowsMatch(
            before, after, self.rows - 1, 0
        )

    def _forcePageAdvance(self, before: np.ndarray, target: float) -> bool:
        """Push config-sized page scrolls until the grid clearly advanced or ends."""
        current = before
        for attempt in range(3):
            self._focusGrid()
            self._wheel(self.configNotches)
            after = self._capture()
            if self._finishPageScroll(before, after):
                return True
            moved, _ = self._displacement(before, after)
            mag = self._changeMagnitude(current, after)
            logger.debug(
                "%s: force page attempt %s — moved=%s Δ=%.1f",
                self.name,
                attempt + 1,
                None if moved is None else f'{moved:.0f}px',
                mag,
            )
            if moved is not None and moved >= target * 0.85:
                return self._finishPageScroll(before, after)
            shifted = self._rowsShifted(current, after)
            if shifted < 0 and mag >= 8.0:
                # Identical-icon wall: trust a strong Δ after a focused page wheel,
                # then still clear any measurable overlap.
                return self._finishPageScroll(before, after)
            if not self._changed(current, after) and attempt > 0:
                logger.info("%s: grid will not scroll further — treating as end of list", self.name)
                return False
            current = after
        if self._finishPageScroll(before, self._capture()):
            return True
        logger.warning(
            "%s: forced page scroll still did not advance a page — stopping to avoid re-scan",
            self.name,
        )
        return False

    def _plannedNotches(self, targetPx: float) -> float:
        if self.pxPerNotch:
            return targetPx / self.pxPerNotch
        return self.configNotches * (targetPx / self.rowPitch) / self.rows

    def _effectivePxPerNotch(self) -> float:
        return self.pxPerNotch or self.expectedPxPerNotch

    def _maybeLearn(self, moved: float, sent: float, target: float) -> None:
        """Accept a px/notch sample only when both displacement and rate look sane."""
        if self.pxPerNotch is not None or sent <= 0 or moved <= 0 or not self.rowPitch:
            return

        if abs(target - moved) > self.rowPitch * LEARN_MAX_TARGET_ERROR:
            logger.debug(
                "%s: skip rate sample — moved %.0fpx of %.0f (too far from target)",
                self.name, moved, target,
            )
            return

        learned = moved / sent
        expected = self.expectedPxPerNotch
        if not (PX_PER_NOTCH_RANGE[0] <= learned <= PX_PER_NOTCH_RANGE[1]):
            logger.debug(
                "%s: skip rate sample — %.2f px/notch outside absolute range",
                self.name, learned,
            )
            return
        if abs(learned - expected) / expected > LEARN_MAX_RATE_ERROR:
            logger.debug(
                "%s: skip rate sample — %.2f px/notch too far from expected %.2f",
                self.name, learned, expected,
            )
            return

        self._rateSamples.append(learned)
        logger.info(
            "%s: rate sample %.2f px/notch (%s/%s, expected %.2f)",
            self.name, learned, len(self._rateSamples), MIN_CALIBRATION_SAMPLES, expected,
        )
        if len(self._rateSamples) >= MIN_CALIBRATION_SAMPLES:
            self.pxPerNotch = float(sum(self._rateSamples) / len(self._rateSamples))
            logger.info("%s: locked wheel rate at %.2f px/notch", self.name, self.pxPerNotch)
            savePersistedRate(self.name, self.pxPerNotch, self.rowPitch)

    def _scrollRows(self, rowCount: float) -> bool:
        """Move the grid down `rowCount` rows. False when it cannot scroll at all."""
        target = rowCount * self.rowPitch + self.carryPx

        self._parkOnGrid()
        before = self._capture()

        sent = self._plannedNotches(target)
        self._wheel(sent)
        after = self._capture()
        moved, score = self._displacement(before, after)

        if moved is None:
            if self._changed(before, after):
                logger.debug(
                    "%s: step displacement unmeasurable (score %.2f) but grid changed — trusting the wheel",
                    self.name, score,
                )
                self.carryPx = 0.0
                return True
            # No measurable shift and no visible change — retry once, then give up.
            self._wheel(sent)
            after = self._capture()
            moved, score = self._displacement(before, after)
            if (moved is None or moved <= 2) and not self._changed(before, after):
                logger.info("%s: grid will not scroll further — treating as end of list", self.name)
                return False
            if moved is None:
                self.carryPx = 0.0
                return True

        elif moved <= 2:
            # Template match can report dy=0 when adjacent rows look identical
            # (many copies of the same echo). Only treat as the end when the
            # whole grid capture is unchanged.
            if self._changed(before, after):
                logger.debug(
                    "%s: displacement %.0fpx but grid changed — not end of list",
                    self.name, moved,
                )
                self.carryPx = 0.0
                return True
            self._wheel(sent)
            after = self._capture()
            moved, score = self._displacement(before, after)
            if (moved is None or moved <= 2) and not self._changed(before, after):
                logger.info("%s: grid will not scroll further — treating as end of list", self.name)
                return False
            if moved is None or moved <= 2:
                self.carryPx = 0.0
                return True

        # Learn from the first wheel event only — corrections distort the ratio
        # when the displacement match was already a few dozen pixels off.
        initialSent = sent
        initialMoved = moved

        for _ in range(MAX_CORRECTIONS):
            residual = target - moved
            if abs(residual) <= TOLERANCE_PX:
                break
            perNotch = self._effectivePxPerNotch()
            if not perNotch:
                break
            correction = residual / perNotch
            self._wheel(correction)
            corrected, score = self._displacement(before, self._capture())
            if corrected is None or abs(target - corrected) >= abs(residual):
                break
            sent += correction
            moved = corrected

        self._maybeLearn(initialMoved, initialSent, target)

        limit = self.rowPitch * MAX_CARRY_ROWS
        residual = target - (moved or 0)
        self.carryPx = max(-limit, min(limit, residual))

        logger.debug(
            "%s: advanced %.0fpx of %.0f (%.1f notches, %.2f px/notch, carrying %.0fpx)",
            self.name, moved or 0, target, sent, self._effectivePxPerNotch(), self.carryPx,
        )
        if moved and abs(residual) > self.rowPitch * 0.4:
            logger.warning(
                "%s: page scroll off by %.0fpx (~%.1f rows) — rows may be missed or rescanned",
                self.name, residual, residual / self.rowPitch,
            )
        return True

    def _scrollBurst(self, rowCount: float) -> bool:
        """Advance `rowCount` rows with one wheel burst. False at end of list."""
        target = rowCount * self.rowPitch + self.carryPx

        self._focusGrid()
        before = self._capture()
        sent = self._plannedNotches(target)
        self._wheel(sent)
        after = self._capture()

        moved, score = self._displacement(before, after)
        if moved is not None and moved > 2:
            # Catastrophic under-scroll: wheel almost no-op (focus on panel /
            # submenu). Identical inventory tiles (common for weapons) make
            # template displacement report ~5-15px even when a full page moved.
            changeMag = self._changeMagnitude(before, after)
            if moved < target * 0.25:
                # Tiny measured move: identical-tile full page or stuck. Always
                # clear trailing-row overlap before accepting (Hollow re-read).
                if self._finishPageScroll(before, after):
                    logger.debug(
                        "%s: displacement only %.0fpx of %.0f but page finished (Δ=%.1f)",
                        self.name, moved, target, changeMag,
                    )
                    self.carryPx = 0.0
                    return True
                logger.warning(
                    "%s: burst under-scrolled (%.0f of %.0f px, Δ=%.1f) — forcing page notches",
                    self.name, moved, target, changeMag,
                )
                if not self._forcePageAdvance(before, target):
                    return False
                self.carryPx = 0.0
                return True

            residual = target - moved
            # With a locked rate, skip the correction pass unless we are clearly
            # off — corrections were doubling the settle cost on every page.
            # Skip corrections when displacement looks bogus relative to a changed grid.
            if abs(residual) > self.rowPitch * 0.25 and moved >= target * 0.5:
                correction = residual / self._effectivePxPerNotch()
                self._wheel(correction)
                after = self._capture()
                corrected, _ = self._displacement(before, after)
                if corrected is not None and abs(target - corrected) < abs(residual):
                    moved = corrected
            # Even a "good" displacement can leave one row glued (Hollow re-read).
            if not self._finishPageScroll(before, self._capture()):
                return False
            limit = self.rowPitch * MAX_CARRY_ROWS
            self.carryPx = max(-limit, min(limit, target - moved))
            logger.debug(
                "%s: burst advanced %.0fpx of %.0f (carrying %.0fpx)",
                self.name, moved, target, self.carryPx,
            )
            return True

        # A whole-page burst leaves almost no shared content, so an unmeasurable
        # shift is expected. Confirm with row-band matching when possible.
        changeMag = self._changeMagnitude(before, after)
        if self._finishPageScroll(before, after):
            self.carryPx = -self.rowPitch * 0.1
            logger.debug(
                "%s: burst unmeasurable (score %.2f) but page finished (Δ=%.1f, carry %.0fpx)",
                self.name, score, changeMag, self.carryPx,
            )
            return True
        if self._changed(before, after):
            logger.warning(
                "%s: burst unmeasurable with no page-advance match (Δ=%.1f) — forcing page notches",
                self.name, changeMag,
            )
            if not self._forcePageAdvance(before, target):
                return False
            self.carryPx = 0.0
            return True

        self._wheel(sent)
        after = self._capture()
        if self._finishPageScroll(before, after):
            self.carryPx = 0.0
            return True

        logger.info("%s: grid will not scroll further — treating as end of list", self.name)
        return False

    def scrollPage(self) -> bool:
        """Advance one full page. False when the grid is already at the end."""
        if self.rowPitch is None:
            self._parkOnGrid()
            self.rowPitch = self._measureRowPitch(self._capture())

        # Persisted / locked rate → one burst. Otherwise calibrate with one-row
        # steps until locked, then burst the remainder.
        if self.pxPerNotch is not None:
            return self._scrollBurst(self.rows)

        remaining = float(self.rows)
        while remaining > 0:
            step = min(CALIBRATION_STEP_ROWS, remaining)
            if not self._scrollRows(step):
                return False
            remaining -= step
            if self.pxPerNotch is not None and remaining > 0:
                return self._scrollBurst(remaining)
        return True
