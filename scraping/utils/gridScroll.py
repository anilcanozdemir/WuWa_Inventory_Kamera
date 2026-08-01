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
        if persisted is not None:
            self.pxPerNotch = persisted
            logger.info("%s: using persisted wheel rate %.2f px/notch", name, persisted)

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
        self.controller.moveMouse(x + w // 2, y + h // 2, 0.05)

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

        self._parkOnGrid()
        before = self._capture()
        sent = self._plannedNotches(target)
        self._wheel(sent)
        after = self._capture()

        moved, score = self._displacement(before, after)
        if moved is not None and moved > 2:
            residual = target - moved
            # With a locked rate, skip the correction pass unless we are clearly
            # off — corrections were doubling the settle cost on every page.
            if abs(residual) > self.rowPitch * 0.25:
                correction = residual / self._effectivePxPerNotch()
                self._wheel(correction)
                corrected, _ = self._displacement(before, self._capture())
                if corrected is not None and abs(target - corrected) < abs(residual):
                    moved = corrected
            limit = self.rowPitch * MAX_CARRY_ROWS
            self.carryPx = max(-limit, min(limit, target - moved))
            logger.debug(
                "%s: burst advanced %.0fpx of %.0f (carrying %.0fpx)",
                self.name, moved, target, self.carryPx,
            )
            return True

        # A whole-page burst leaves almost no shared content, so an unmeasurable
        # shift is expected. Only an unchanged image means the list really ended.
        if self._changed(before, after):
            self.carryPx = 0.0
            logger.debug("%s: burst unmeasurable (score %.2f) but grid changed", self.name, score)
            return True

        self._wheel(sent)
        after = self._capture()
        if self._changed(before, after):
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
