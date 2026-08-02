import os
import cv2
import time
import string
import logging
import numpy as np
from pathlib import Path
from difflib import get_close_matches as getMatches
from collections import defaultdict

from scraping.utils import (
    echoesID, echoStats, sonataName
)
from scraping.utils import (
    screenshot, imageToString, convertToBlackWhite,
    WindowsInputController, GridPageScroller
)
from game.screenInfo import ScreenInfo
from game.menu import MainMenuController
from properties.config import cfg

logger = logging.getLogger('EchoScraper')

# Constants
ROWS, COLS = 4, 6

# processGridEcho outcomes.
CELL_OK = 'ok'            # a valid echo was read and stored
CELL_STOP = 'stop'        # recognised but below the rarity/level filter -> stop
CELL_MISS = 'miss'        # nothing recognised (click likely missed the card)

# Consecutive misses that trigger a detail-panel reset.
MISS_RESET_STREAK = 3

# Circular set badge next to +level. Matching these is ~instant and avoids the
# panel scroll that previously ran on every echo (and parked the cursor off the
# grid, breaking page scrolling). Unknown icons fall back to OCR once and are
# saved so the next encounter is free.
SONATA_ICON_DIR = Path(__file__).resolve().parents[1] / 'assets' / 'sonata'
# Matching the template at the same size as the crop leaves matchTemplate a 1x1
# result, so it cannot absorb any misalignment: measured on the learned set, a
# 1-3px shift dropped a correct badge to as low as 0.046 and let the WRONG badge
# win 37% of the time. Searching a smaller inner patch inside the full crop
# gives the match room to slide. With that, on deliberately degraded crops the
# correct badge never scored below 0.919 while the best wrong badge peaked at
# 0.870, so 0.85 plus a margin over the runner-up separates both cleanly.
SONATA_MATCH_MIN = 0.85
SONATA_MATCH_MARGIN = 0.05
SONATA_ICON_SIZE = (44, 44)
SONATA_TEMPLATE_INNER = 32
_SONATA_TEMPLATES: list[tuple[str, np.ndarray]] | None = None


def _canon(iconBgrOrRgb: np.ndarray) -> np.ndarray:
    return cv2.resize(iconBgrOrRgb, SONATA_ICON_SIZE, interpolation=cv2.INTER_AREA)


def _loadSonataTemplates() -> list[tuple[str, np.ndarray]]:
    global _SONATA_TEMPLATES
    if _SONATA_TEMPLATES is not None:
        return _SONATA_TEMPLATES

    templates: list[tuple[str, np.ndarray]] = []
    if SONATA_ICON_DIR.is_dir():
        for path in sorted(SONATA_ICON_DIR.glob('*.png')):
            if path.name.startswith('_'):
                continue
            image = cv2.imread(str(path), cv2.IMREAD_COLOR)
            if image is None or image.size == 0:
                continue
            templates.append((path.stem.lower(), image))
    _SONATA_TEMPLATES = templates
    logger.info('Loaded %s sonata icon templates from %s', len(templates), SONATA_ICON_DIR)
    return templates


def _saveSonataTemplate(name: str, iconRgb: np.ndarray) -> None:
    if not name or name not in sonataName:
        return
    SONATA_ICON_DIR.mkdir(parents=True, exist_ok=True)
    path = SONATA_ICON_DIR / f'{name}.png'
    if path.exists():
        return
    # Disk templates are BGR (cv2.imread convention); the live crop is RGB.
    bgr = cv2.cvtColor(iconRgb, cv2.COLOR_RGB2BGR)
    cv2.imwrite(str(path), bgr)
    _loadSonataTemplates().append((name, bgr.copy()))
    logger.info('Learned sonata icon template: %s', name)


def _innerPatch(canonBgr: np.ndarray) -> np.ndarray:
    """Centre patch of a canonical icon, used as the sliding template."""
    off = (SONATA_ICON_SIZE[0] - SONATA_TEMPLATE_INNER) // 2
    return canonBgr[off:off + SONATA_TEMPLATE_INNER, off:off + SONATA_TEMPLATE_INNER]


def _matchSonataIcon(iconRgb: np.ndarray) -> tuple[str | None, float]:
    """Return (sonataName, score) for the best template match, or (None, score).

    Matches in colour at a canonical size, sliding each template's centre patch
    across the crop so a few pixels of ROI drift cannot sink a correct match. A
    match must also beat the runner-up by a margin, which is what keeps a badge
    that has no template yet from being mistaken for the nearest one it resembles.
    """
    if iconRgb is None or iconRgb.size == 0:
        return None, 0.0

    # Templates on disk are BGR; the live crop is RGB. Compare in a common
    # order by flipping the live crop's channels to BGR.
    hay = _canon(cv2.cvtColor(iconRgb, cv2.COLOR_RGB2BGR))
    scored: list[tuple[float, str]] = []
    for name, template in _loadSonataTemplates():
        result = cv2.matchTemplate(hay, _innerPatch(_canon(template)), cv2.TM_CCOEFF_NORMED)
        if result.size:
            scored.append((float(result.max()), name))
    if not scored:
        return None, 0.0

    scored.sort(reverse=True)
    bestScore, bestName = scored[0]
    margin = bestScore - scored[1][0] if len(scored) > 1 else 1.0
    if bestScore >= SONATA_MATCH_MIN and margin >= SONATA_MATCH_MARGIN:
        return bestName, bestScore
    return None, bestScore

def matchStats(text):
    stats = set(echoStats)
    results = []
    i = 0
    while i < len(text):
        if i < len(text) - 1:
            combinedWord = text[i] + text[i + 1]
            if combinedWord in stats:
                results.append(combinedWord)
                i += 2
                continue
        if text[i] in stats:
            results.append(text[i])
        i += 1
    return results

def setupRarityDetection():
    rarityColors = {
        5: np.array([90, 230, 255]),
        4: np.array([255, 109, 202]),
        3: np.array([211, 180, 89]),
        2: np.array([94, 195, 92]),
        1: np.array([225, 236, 239])
    }

    tolerance = 10
    bounds = {rarity: (color - tolerance, color + tolerance) for rarity, color in rarityColors.items()}

    return bounds

RARITY_BOUNDS = setupRarityDetection()

def getRarity(image: np.ndarray):
    for rarity, (lower, upper) in RARITY_BOUNDS.items():
        if np.any(cv2.inRange(image, lower, upper)):
            return rarity
    return 1

def getEchoPages(screenInfo: ScreenInfo) -> int:
    image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)[screenInfo.echoes.page.y:screenInfo.echoes.page.y + screenInfo.echoes.page.h, screenInfo.echoes.page.x:screenInfo.echoes.page.x + screenInfo.echoes.page.w]
    echoCount = imageToString(image, allowedChars=string.digits + '/').split('/')[0]
    
    try: return int(echoCount), int(np.ceil(int(echoCount) / 24))
    except ValueError: return 24, 1

def processEcho(name: str, level: int, tuneLv: int, sonata: str, rarity: int, stats: dict) -> dict[str, dict[int, int, dict]]:
    result = getMatches(name, echoesID, 1, 0.9)
    if result: name = result[0]
    
    echoID = str(echoesID.get(name, name))
    return {
        echoID: {
            'level': level,
            'tuneLv': tuneLv,
            'sonata': sonata,
            'rarity': rarity,
            'stats': stats
        }
    }

def processStats(image: np.ndarray, screenInfo: ScreenInfo, _cache: dict) -> dict[str:int]:
    stats = defaultdict(dict)
    tuneLv = 0

    nameImage = image[
        screenInfo.echoes.fullStatsName.y:screenInfo.echoes.fullStatsName.y + screenInfo.echoes.fullStatsName.h,
        screenInfo.echoes.fullStatsName.x:screenInfo.echoes.fullStatsName.x + screenInfo.echoes.fullStatsName.w
    ]
    nameImage = convertToBlackWhite(nameImage)
    nameHash = hash(nameImage.tobytes())

    valueImage = image[
        screenInfo.echoes.fullStatsValue.y:screenInfo.echoes.fullStatsValue.y + screenInfo.echoes.fullStatsValue.h,
        screenInfo.echoes.fullStatsValue.x:screenInfo.echoes.fullStatsValue.x + screenInfo.echoes.fullStatsValue.w
    ]
    valueImage = convertToBlackWhite(valueImage)
    valueHash = hash(valueImage.tobytes())

    if nameHash in _cache:
        names = _cache[nameHash]
    else:
        names = imageToString(nameImage, allowedChars=string.ascii_letters).lower().split('\n')
        names = matchStats(names)
        _cache[nameHash] = names

    if valueHash in _cache:
        values = _cache[valueHash]
    else:
        values = imageToString(valueImage, allowedChars=string.digits + '.%').split()
        _cache[valueHash] = values
    tuneLv = max(0, len(values) - 2)


    for index, (statName, statValue) in enumerate(zip(names, values)):
        statName = echoStats.get(statName, statName)

        if index < 2: stat = 'main'
        else: stat = 'sub'
        
        try:
            if statValue.endswith('%'):
                stats[stat].update({f"{statName}%": float(statValue[:-1])})
            else:
                stats[stat].update({statName: int(statValue)})
        except:
            stats[stat].update({statName: statValue})

    return tuneLv, dict(stats)

def _resetDetailPanel(controller: WindowsInputController, screenInfo: ScreenInfo) -> None:
    """Force the echo detail panel back to the top.

    A panel left scrolled down makes the name/level ROI read the wrong part of
    the card, so every following cell reads as a miss until something scrolls it
    back — this is what produced the exactly-24-cell 'dead pages' in scan logs.
    Scrolling up past the top is clamped by the game, so over-scrolling is a
    safe way to guarantee the panel is home again.
    """
    controller.moveMouse(screenInfo.echoes.mouseMovement.x, screenInfo.echoes.mouseMovement.y, .2)
    controller.mouseScroll(abs(screenInfo.scroll.sonata.y) * 2, .3)


def _ocrSonataByScrolling(controller: WindowsInputController, screenInfo: ScreenInfo) -> str:
    """Legacy fallback: scroll the detail panel and OCR the Sonata Effect block."""
    controller.moveMouse(screenInfo.echoes.mouseMovement.x, screenInfo.echoes.mouseMovement.y, .2)
    controller.mouseScroll(-abs(screenInfo.scroll.sonata.y), .3)
    image = screenshot(
        screenInfo.echoes.sonata.x, screenInfo.echoes.sonata.y,
        screenInfo.echoes.sonata.w, screenInfo.echoes.sonata.h,
        monitor=screenInfo.monitor,
    )
    text = imageToString(image, '', bannedChars=' ').lower()
    sonata = ''
    for name in sonataName:
        if name in text:
            sonata = name
            break
    _resetDetailPanel(controller, screenInfo)
    return sonata


def getSonata(
    image: np.ndarray,
    screenInfo: ScreenInfo,
    _cache: dict,
    controller: WindowsInputController | None = None,
) -> str:
    """Read the sonata from the circular set badge next to +level.

    No panel scrolling on the happy path. Unknown badges are OCR'd once via the
    old scroll path and then saved under assets/sonata/ for later matches.
    """
    iconRoi = getattr(screenInfo.echoes, 'sonataIcon', None)
    if iconRoi is None or not iconRoi.w or not iconRoi.h:
        if controller is None:
            return ''
        return _ocrSonataByScrolling(controller, screenInfo)

    icon = image[
        int(iconRoi.y):int(iconRoi.y + iconRoi.h),
        int(iconRoi.x):int(iconRoi.x + iconRoi.w),
    ]
    iconHash = hash(icon.tobytes())
    if iconHash in _cache:
        return _cache[iconHash]

    name, score = _matchSonataIcon(icon)
    if name:
        logger.debug('sonata icon matched %s (score %.3f)', name, score)
        _cache[iconHash] = name
        return name

    if controller is None:
        logger.debug('sonata icon unmatched (best %.3f) and no controller for OCR fallback', score)
        _cache[iconHash] = ''
        return ''

    logger.info('sonata icon unmatched (best %.3f) — learning via panel OCR', score)
    sonata = _ocrSonataByScrolling(controller, screenInfo)
    if sonata:
        _saveSonataTemplate(sonata, icon)
    _cache[iconHash] = sonata
    return sonata

def parseEchoLevel(lines: list[str]) -> int:
    """Pick the echo level from OCR card lines.

    The card usually reads `name / level / cost`, but OCR may drop or reorder
    lines, so prefer any standalone integer in 0..25 over a fixed index.
    Prefer a non-zero candidate when both cost (1/3/4) and level appear.
    """
    candidates = []
    for text in lines[1:]:
        try:
            value = int(text)
        except (TypeError, ValueError):
            continue
        if 0 <= value <= 25:
            candidates.append(value)
    if candidates:
        nonzero = [c for c in candidates if c > 0]
        return nonzero[0] if nonzero else candidates[0]
    if len(lines) > 2:
        try:
            return min(25, int(lines[2]))
        except (TypeError, ValueError):
            pass
    return 0


def _readEchoLevel(image: np.ndarray, screenInfo: ScreenInfo, lines: list[str]) -> int:
    """Prefer a dedicated +level ROI; fall back to full-card OCR lines."""
    levelRoi = getattr(screenInfo.echoes, 'echoLevel', None)
    if levelRoi is not None and levelRoi.w and levelRoi.h:
        crop = image[
            int(levelRoi.y):int(levelRoi.y + levelRoi.h),
            int(levelRoi.x):int(levelRoi.x + levelRoi.w),
        ]
        raw = imageToString(
            convertToBlackWhite(crop), '', allowedChars=string.digits,
        ).strip()
        digits = ''.join(ch for ch in raw if ch.isdigit())
        if digits:
            try:
                value = int(digits[:2] if len(digits) > 2 else digits)
                if 0 <= value <= 25:
                    return value
            except ValueError:
                pass
    return parseEchoLevel(lines)


def processGridEcho(controller: WindowsInputController, screenInfo: ScreenInfo, echoes: list, image: np.ndarray, _cache: dict[str, list]) -> tuple[dict[str, int], list[dict[str, dict[str, int]]]]:

    echoCard = image[screenInfo.echoes.echoCard.y:screenInfo.echoes.echoCard.y + screenInfo.echoes.echoCard.h, screenInfo.echoes.echoCard.x:screenInfo.echoes.echoCard.x + screenInfo.echoes.echoCard.w]
    echoHash = hash(echoCard.tobytes())
    if echoHash in _cache:
        info = _cache[echoHash]
    else:
        info = [imageToString(echoCard, '', bannedChars=' +').lower().split('\n')]
        _cache[echoHash] = info

    lines = info[0] if info else []
    name = lines[0] if lines else ''
    if name and name not in echoesID:
        # OCR often drops/garbles a letter; accept a close known echo name.
        matched = getMatches(name, echoesID, 1, 0.8)
        if matched:
            name = matched[0]
    
    if name in echoesID:
        try:
            rarity = info[1][0]
        except:
            rarity = getRarity(echoCard)
            _cache[echoHash].append(rarity)
        
        if rarity >= cfg.get(cfg.echoMinRarity):
            level = _readEchoLevel(image, screenInfo, lines)

            if level >= cfg.get(cfg.echoMinLevel):
                tuneLv, stats = processStats(image, screenInfo, _cache)
                sonata = getSonata(image, screenInfo, _cache, controller)
                echoes.append(processEcho(name, level, tuneLv, sonata, rarity, stats))
                return CELL_OK
        return CELL_STOP

    return CELL_MISS

def echoScraper(controller: WindowsInputController, x: float, y: float, screenInfo: ScreenInfo) -> tuple[list, int]:
    """Scrape the echo grid. Returns (echoes, inventoryEchoCount)."""
    echoes = list()
    _cache = dict()
    menu = MainMenuController()

    if menu.isMenu() and not menu.ensureGameplay(controller):
        return echoes, 0

    controller.pressKey(cfg.get(cfg.inventoryKeybind), 2, False)
    time.sleep(0.5)
    if menu.isMenu():
        return echoes, 0

    controller.leftClick(x, y)

    echoCount, pages = getEchoPages(screenInfo)
    status = CELL_MISS
    missStreak = 0
    scroller = GridPageScroller(controller, screenInfo, screenInfo.echoes, ROWS, COLS, 'echoes')
    scroller.scrollToTop(pages)

    def _scanPage(page: int) -> tuple[int, str, bool]:
        """Walk one page of cells. Returns (recognised, lastStatus, done)."""
        nonlocal missStreak
        pageRecognised = 0
        pageStatus = CELL_MISS
        for row in range(ROWS):
            for col in range(COLS):
                # The final page is partly empty; stop once every echo the
                # inventory reported has been visited. Comparing the global cell
                # index against echoCount also handles counts that are an exact
                # multiple of a page, which the previous remainder check did not.
                if page * (ROWS * COLS) + row * COLS + col >= echoCount:
                    return pageRecognised, pageStatus, True
                center_x = screenInfo.echoes.start.x + (col * (screenInfo.echoes.start.w + screenInfo.offsets.page.x)) + screenInfo.echoes.start.w // 2
                center_y = screenInfo.echoes.start.y + (row * (screenInfo.echoes.start.h + screenInfo.offsets.page.y)) + screenInfo.echoes.start.h // 2

                pageStatus = _scanCell(controller, screenInfo, echoes, center_x, center_y, _cache)

                # A run of misses means the panel itself is wrong, not the click.
                # Reset it and re-read the already-selected card, which caps the
                # damage at MISS_RESET_STREAK cells instead of a whole page.
                if pageStatus == CELL_MISS:
                    missStreak += 1
                    if missStreak >= MISS_RESET_STREAK:
                        logger.warning(
                            "Echoes: %s misses in a row — resetting the detail panel", missStreak,
                        )
                        _resetDetailPanel(controller, screenInfo)
                        image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
                        pageStatus = processGridEcho(controller, screenInfo, echoes, image, _cache)
                        if pageStatus != CELL_MISS:
                            missStreak = 0
                    # Half a page of misses → grid alignment is wrong; nudge and
                    # re-click instead of burning the rest of the page as unread.
                    if pageStatus == CELL_MISS and missStreak >= COLS * 2:
                        logger.warning(
                            "Echoes: %s misses — mid-page realign",
                            missStreak,
                        )
                        _resetDetailPanel(controller, screenInfo)
                        scroller._parkOnGrid()
                        if scroller.rowPitch and scroller.pxPerNotch:
                            half = (0.5 * scroller.rowPitch) / scroller.pxPerNotch
                            scroller._wheel(-half)
                            time.sleep(0.25)
                            scroller._wheel(half)
                            time.sleep(0.25)
                        missStreak = 0
                        pageStatus = _scanCell(controller, screenInfo, echoes, center_x, center_y, _cache)
                        if pageStatus == CELL_MISS:
                            missStreak = 1
                else:
                    missStreak = 0

                if pageStatus == CELL_STOP:
                    return pageRecognised, pageStatus, True
                if pageStatus == CELL_OK:
                    pageRecognised += 1
                else:
                    # Dropped cells shift every later entry, so record exactly
                    # where they happen instead of only noticing the shortfall.
                    logger.warning(
                        "Echoes: page %s row %s col %s unread after retry (%s collected so far)",
                        page + 1, row, col, len(echoes),
                    )
        return pageRecognised, pageStatus, False

    def _realignAfterDeadPage() -> None:
        """Resettle the grid after a page where every click missed."""
        _resetDetailPanel(controller, screenInfo)
        scroller._parkOnGrid()
        # Nudge up half a row then back so clicks land on cards again if the
        # previous page burst left the grid half-row misaligned.
        if scroller.rowPitch and scroller.pxPerNotch:
            half = (0.5 * scroller.rowPitch) / scroller.pxPerNotch
            scroller._wheel(-half)
            time.sleep(0.35)
            scroller._wheel(half)
            time.sleep(0.35)
        else:
            time.sleep(0.35)

    for page in range(pages):
        missStreak = 0
        pageRecognised, status, done = _scanPage(page)
        if done:
            del _cache
            return echoes, echoCount

        logger.info("Echoes: page %s/%s scanned, %s collected", page + 1, pages, len(echoes))
        if pageRecognised == 0:
            logger.warning(
                "Echoes: page %s recognised 0 cards — realigning and retrying page",
                page + 1,
            )
            _realignAfterDeadPage()
            # Fresh captures after realign; hashed misses must not poison the retry.
            _cache.clear()
            missStreak = 0
            beforeRetry = len(echoes)
            pageRecognised, status, done = _scanPage(page)
            if done:
                del _cache
                return echoes, echoCount
            logger.info(
                "Echoes: page %s retry recognised %s (collected %s → %s)",
                page + 1, pageRecognised, beforeRetry, len(echoes),
            )
            if pageRecognised == 0:
                logger.warning(
                    "Echoes: page %s still recognised 0 cards after retry — clicks likely missed the grid",
                    page + 1,
                )

        if page < pages - 1 and status != CELL_STOP and not scroller.scrollPage():
            break

    del _cache
    return echoes, echoCount


def _scanCell(controller, screenInfo, echoes, center_x, center_y, _cache) -> str:
    """Click a grid cell once, then re-read the panel if nothing was recognised.

    The retry deliberately does NOT click again: the click has already
    registered, and a second click on an echo is treated as a double click by
    the game (which opens a submenu and then blocks grid scrolling entirely).
    Most misses are just the detail panel not having repainted yet, so giving it
    another capture is enough.
    """
    controller.leftClick(center_x, center_y)
    image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
    status = processGridEcho(controller, screenInfo, echoes, image, _cache)
    if status != CELL_MISS:
        return status

    time.sleep(0.2)
    image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
    return processGridEcho(controller, screenInfo, echoes, image, _cache)
