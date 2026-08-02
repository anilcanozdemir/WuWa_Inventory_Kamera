import logging
import re
import string
import time

import numpy as np
from difflib import get_close_matches as getMatches

from scraping.utils import weaponsID, itemsID
from scraping.utils import (
    screenshot, convertToBlackWhite, imageToString,
    WindowsInputController, GridPageScroller
)
from game.screenInfo import ScreenInfo
from game.menu import MainMenuController
from properties.config import cfg

logger = logging.getLogger('WeaponScraper')

# Constants
ROWS, COLS = 4, 6
WEAPON_ASCENSION_LEVELS = [20, 40, 50, 60, 70, 80, 90]
LEVEL_PAIR_RE = re.compile(r'(\d{1,3})\s*/\s*(\d{1,3})')
ENERGY_CORE_KEYS = {
    'basicenergycore',
    'mediumenergycore',
    'advancedenergycore',
    'premiumenergycore',
}


def _energyCoreNames(inventory: dict) -> list[str]:
    """Names of energy-core stacks kept while scanning the weapons tab."""
    idToName = {
        str(itemsID[k]['id']): itemsID[k].get('name', k)
        for k in ENERGY_CORE_KEYS if k in itemsID
    }
    return [idToName[str(i)] for i in inventory if str(i) in idToName]

def getWeaponPages(screenInfo: ScreenInfo) -> tuple[int, int]:
    image = convertToBlackWhite(screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)[screenInfo.weapons.page.y:screenInfo.weapons.page.y + screenInfo.weapons.page.h, screenInfo.weapons.page.x:screenInfo.weapons.page.x + screenInfo.weapons.page.w])
    raw = imageToString(image, '', allowedChars=string.digits + '/')
    weaponCount = raw.split('/')[0]
    try:
        count = int(weaponCount)
        if count <= 0:
            raise ValueError(weaponCount)
        return count, int(np.ceil(count / 24))
    except ValueError:
        logger.warning("Weapons: could not parse inventory counter %r — retrying", raw)
        time.sleep(0.35)
        image = convertToBlackWhite(screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)[screenInfo.weapons.page.y:screenInfo.weapons.page.y + screenInfo.weapons.page.h, screenInfo.weapons.page.x:screenInfo.weapons.page.x + screenInfo.weapons.page.w])
        raw = imageToString(image, '', allowedChars=string.digits + '/')
        weaponCount = raw.split('/')[0]
        try:
            count = int(weaponCount)
            if count <= 0:
                raise ValueError(weaponCount)
            return count, int(np.ceil(count / 24))
        except ValueError:
            logger.error("Weapons: inventory counter still unreadable %r — aborting weapon scan", raw)
            return 0, 0

def _roi(image: np.ndarray, box, originX: int, originY: int) -> np.ndarray:
    """Crop an absolute screen ROI out of a screenshot (origin usually 0,0)."""
    x = int(box.x - originX)
    y = int(box.y - originY)
    return image[y:y + int(box.h), x:x + int(box.w)]


def processItem(name: str, valueText: str) -> tuple[str, int]:
    itemID = itemsID[name]['id']
    try:
        value = int(valueText)
    except ValueError:
        value = 1
    return itemID, value

def processWeapon(name: str, levelText: str, rankText: str) -> dict[str, dict[str, int]]:
    weaponID = weaponsID[name]['id']
    level = levelText.split('/')
    return {
        weaponID: {
            'level': int(level[0]),
            'ascension': WEAPON_ASCENSION_LEVELS.index(int(level[1])),
            'rank': int(rankText)
        }
    }

def _readWeaponLevel(image: np.ndarray, screenInfo: ScreenInfo, _cache: dict, originX: int = 0, originY: int = 0) -> str:
    """OCR the Level N/N band; return 'curr/max' or ''."""
    levelImage = _roi(image, screenInfo.weapons.level, originX, originY)
    if levelImage.size == 0:
        return ''
    levelHash = hash(levelImage.tobytes())
    if levelHash in _cache:
        return _cache[levelHash]

    def _parse(raw: str) -> str:
        match = LEVEL_PAIR_RE.search(raw or '')
        if not match:
            return ''
        curr, mx = int(match.group(1)), int(match.group(2))
        if 1 <= curr <= 90 and curr <= mx <= 90:
            return f'{curr}/{mx}'
        return ''

    bw = convertToBlackWhite(levelImage)
    levelText = _parse(imageToString(bw, '', allowedChars=string.digits + '/'))
    if not levelText:
        levelText = _parse(imageToString(bw, ''))
    if not levelText and originX == 0 and originY == 0:
        # Wider band on full-frame captures when the tight ROI clips digits.
        wide = image[
            int(screenInfo.weapons.level.y - 10):int(screenInfo.weapons.level.y + screenInfo.weapons.level.h + 10),
            int(screenInfo.weapons.level.x):int(screenInfo.weapons.level.x + max(screenInfo.weapons.level.w, 420)),
        ]
        if wide.size:
            levelText = _parse(imageToString(convertToBlackWhite(wide), ''))

    if levelText:
        _cache[levelHash] = levelText
    return levelText


def _normKey(text: str) -> str:
    """Lowercase alnum-only key so OCR can match apostrophe / punctuation variants."""
    return ''.join(ch for ch in (text or '').lower() if ch.isalnum())


def _matchName(raw: str) -> str | None:
    """Fuzzy-match OCR text to a weapon or item key; None if nothing close enough."""
    text = _normKey(raw)
    if not text:
        return None
    # Detail panel OCR often glues the rarity digit onto the name ("azureoath4").
    variants = [text]
    stripped = text.rstrip(string.digits)
    if stripped and stripped != text:
        variants.append(stripped)

    weaponKeys = {_normKey(k): k for k in weaponsID}
    itemKeys = {_normKey(k): k for k in itemsID}
    for candidate in variants:
        for cutoff in (0.9, 0.85):
            hit = getMatches(candidate, weaponKeys.keys(), 1, cutoff)
            if hit:
                return weaponKeys[hit[0]]
            hit = getMatches(candidate, itemKeys.keys(), 1, cutoff)
            if hit:
                return itemKeys[hit[0]]
    return None


def _resolveWeaponPanelName(image: np.ndarray, screenInfo: ScreenInfo, _cache: dict, originX: int = 0, originY: int = 0) -> tuple[str | None, str]:
    """OCR the detail-panel name. Only cache successful matches (failed OCR must retry)."""
    nameImage = _roi(image, screenInfo.weapons.name, originX, originY)
    if nameImage.size == 0:
        return None, ''
    bw = convertToBlackWhite(nameImage)
    nameHash = hash(bw.tobytes())
    if nameHash in _cache:
        cached = _cache[nameHash]
        return cached, cached

    # Fast path first; letters-only only if needed.
    for raw in (
        imageToString(bw, '', bannedChars=' ').lower(),
        imageToString(bw, '', allowedChars=string.ascii_letters).lower(),
    ):
        matched = _matchName(raw)
        if matched:
            _cache[nameHash] = matched
            return matched, raw
    return None, imageToString(bw, '', bannedChars=' ').lower()


def processGridItem(
    inventory: dict,
    weapons: list,
    image: np.ndarray,
    screenInfo: ScreenInfo,
    _cache: dict,
    originX: int = 0,
    originY: int = 0,
) -> tuple[bool, tuple | None]:
    """
    Read the selected weapons-tab cell.
    Returns (continueScraping, signature).
    Only name + level (+ rank default 1) — main/substats come from weapon curves.
    """
    name, rawName = _resolveWeaponPanelName(image, screenInfo, _cache, originX, originY)

    if name is None:
        if rawName:
            logger.debug("Weapons: unmatched panel name %r", rawName)
        return True, ('raw', rawName or '')

    if name in itemsID:
        valueImage = convertToBlackWhite(_roi(image, screenInfo.weapons.value, originX, originY))
        valueHash = hash(valueImage.tobytes())
        if valueHash in _cache:
            valueText = _cache[valueHash]
        else:
            valueText = imageToString(valueImage, '', allowedChars=string.digits)
            _cache[valueHash] = valueText

        itemID, value = processItem(name, valueText)
        inventory[itemID] = value
        if name in ENERGY_CORE_KEYS:
            logger.info("Weapons: kept energy core %s x%s", name, value)
        else:
            logger.info("Weapons: kept item %s x%s", name, value)
        return True, ('item', name)

    if name in weaponsID:
        rarity = int(weaponsID[name]['rarity'])
        if rarity >= cfg.get(cfg.weaponsMinRarity):
            levelText = _readWeaponLevel(image, screenInfo, _cache, originX, originY)
            try:
                levelValue = int(levelText.split('/')[0])
            except (TypeError, ValueError, IndexError):
                logger.warning("Weapons: unreadable level %r for %s", levelText, name)
                return True, ('weapon', name, -1, rarity)
            sig = ('weapon', name, levelValue, rarity)
            if levelValue >= cfg.get(cfg.weaponsMinLevel):
                # Rank is not needed for curve stats; default R1 (OCR was a major cost).
                try:
                    weapons.append(processWeapon(name, levelText, '1'))
                except (ValueError, IndexError) as exc:
                    logger.warning("Weapons: failed to parse %s level=%r (%s)", name, levelText, exc)
                return True, sig
            logger.debug("Weapons: %s level %s below min — skipping", name, levelText)
            return True, sig
        return False, ('weapon', name, 0, rarity)

    return True, ('raw', name)


def _gridFingerprint(scroller: GridPageScroller) -> int:
    """Hash the visible grid — unchanged after a scroll means no advance."""
    return hash(scroller._capture().tobytes())


def _clickCell(controller: WindowsInputController, screenInfo: ScreenInfo, row: int, col: int, settle: float = 0.07) -> tuple[np.ndarray, int, int]:
    center_x = screenInfo.weapons.start.x + (col * (screenInfo.weapons.start.w + screenInfo.offsets.page.x)) + screenInfo.weapons.start.w // 2
    center_y = screenInfo.weapons.start.y + (row * (screenInfo.weapons.start.h + screenInfo.offsets.page.y)) + screenInfo.weapons.start.h // 2
    controller.leftClick(center_x, center_y)
    time.sleep(settle)
    # Full frame — panel-only crops clipped the level band and dropped every read.
    image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
    return image, 0, 0


def weaponScraper(controller: WindowsInputController, x: float, y: float, screenInfo: ScreenInfo) -> tuple[dict, list, int]:
    """Scrape the weapon grid. Returns (inventory, weapons, inventoryWeaponCount)."""
    inventory = dict()
    weapons = list()
    _cache = dict()
    menu = MainMenuController()

    if menu.isMenu() and not menu.ensureGameplay(controller):
        return inventory, weapons, 0

    controller.pressKey(cfg.get(cfg.inventoryKeybind), 2, False)
    time.sleep(0.35)
    if menu.isMenu():
        return inventory, weapons, 0

    controller.leftClick(x, y)
    time.sleep(0.3)

    weaponCount, pages = getWeaponPages(screenInfo)
    minRarity = cfg.get(cfg.weaponsMinRarity)
    minLevel = cfg.get(cfg.weaponsMinLevel)
    logger.info(
        "Weapons: inventory count=%s pages=%s minRarity=%s minLevel=%s",
        weaponCount, pages, minRarity, minLevel,
    )
    if weaponCount <= 0 or pages <= 0:
        return inventory, weapons, 0
    continueScraping = True
    scroller = GridPageScroller(controller, screenInfo, screenInfo.weapons, ROWS, COLS, 'weapons')
    # Always start from the top — mid-list open inventory was re-reading the
    # same page after every failed scroll and looked like an endless loop.
    scroller.scrollToTop(pages)
    time.sleep(0.35)

    seenPages: set[int] = set()
    maxPages = pages + 2
    # Last row of OCR signatures from the previous page — if the next page's
    # first row matches, the scroll left a 1-row overlap (extra Hollow etc.).
    prevTail: list[tuple] = []

    for page in range(maxPages):
        if len(weapons) >= weaponCount:
            break

        fingerprint = _gridFingerprint(scroller)
        if fingerprint in seenPages:
            logger.warning(
                "Weapons: page %s grid identical to an earlier page — scroll did not advance, stopping (%s collected)",
                page + 1, len(weapons),
            )
            break
        seenPages.add(fingerprint)

        pageStart = len(weapons)
        pageMisses = 0
        pageSigs: list[tuple] = []
        row = 0
        while row < ROWS:
            # Snapshot so a detected top-row overlap can be rolled back cheaply.
            rowWeaponStart = len(weapons)
            rowInvSnapshot = dict(inventory)
            rowSigs: list[tuple] = []

            for col in range(COLS):
                if len(weapons) >= weaponCount:
                    del _cache
                    logger.info("Weapons: reached reported count=%s collected=%s", weaponCount, len(weapons))
                    return inventory, weapons, weaponCount

                image, originX, originY = _clickCell(controller, screenInfo, row, col)
                beforeCount = len(weapons)
                beforeItems = len(inventory)

                def _floorStop() -> tuple[dict, list, int]:
                    _cache.clear()
                    minR = cfg.get(cfg.weaponsMinRarity)
                    minL = cfg.get(cfg.weaponsMinLevel)
                    cores = _energyCoreNames(inventory)
                    logger.info(
                        "Weapons: rarity/level floor (minRarity=%s minLevel=%s) — "
                        "stopping with %s weapons + %s energy cores %s (bag OCR %s, reads=%s)",
                        minR, minL, len(weapons), len(cores), cores, weaponCount,
                        len(weapons) + len(inventory),
                    )
                    return inventory, weapons, len(weapons) + len(inventory)

                def _cellChanged() -> bool:
                    return len(weapons) > beforeCount or len(inventory) > beforeItems

                continueScraping, sig = processGridItem(
                    inventory, weapons, image, screenInfo, _cache, originX, originY,
                )
                if not continueScraping:
                    return _floorStop()
                if not _cellChanged():
                    time.sleep(0.18)
                    image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
                    originX, originY = 0, 0
                    continueScraping, sig = processGridItem(
                        inventory, weapons, image, screenInfo, _cache, originX, originY,
                    )
                    if not continueScraping:
                        return _floorStop()
                if not _cellChanged():
                    image, originX, originY = _clickCell(controller, screenInfo, row, col, settle=0.2)
                    continueScraping, sig = processGridItem(
                        inventory, weapons, image, screenInfo, _cache, originX, originY,
                    )
                    if not continueScraping:
                        return _floorStop()

                rowSigs.append(sig or ('miss', row, col))
                pageSigs.append(rowSigs[-1])

                if not _cellChanged():
                    pageMisses += 1
                    logger.warning(
                        "Weapons: page %s row %s col %s unread (collected %s/%s)",
                        page + 1, row, col, len(weapons), weaponCount,
                    )

            # OCR overlap check on row 0 only — no separate peek pass.
            if page > 0 and row == 0 and prevTail:
                matched = sum(1 for a, b in zip(rowSigs, prevTail) if a == b)
                if matched >= max(4, COLS - 1):
                    logger.warning(
                        "Weapons: page %s top row matches previous tail (%s/%s) — "
                        "rolling back and nudging 1 row",
                        page + 1, matched, COLS,
                    )
                    del weapons[rowWeaponStart:]
                    inventory.clear()
                    inventory.update(rowInvSnapshot)
                    pageSigs = pageSigs[:-COLS] if len(pageSigs) >= COLS else []
                    pageMisses = 0
                    scroller._focusGrid()
                    if not scroller._scrollRows(1.0):
                        logger.info("Weapons: could not nudge past overlap — done (%s collected)", len(weapons))
                        continueScraping = False
                        break
                    time.sleep(0.2)
                    fingerprint = _gridFingerprint(scroller)
                    seenPages.add(fingerprint)
                    continue  # rescan row 0 after nudge

            row += 1

        if not continueScraping and page > 0 and len(weapons) == pageStart:
            break

        if len(pageSigs) >= COLS:
            prevTail = pageSigs[-COLS:]

        logger.info(
            "Weapons: page %s/%s scanned, +%s this page, %s collected (%s unread cells)",
            page + 1, maxPages, len(weapons) - pageStart, len(weapons), pageMisses,
        )

        if len(weapons) >= weaponCount or not continueScraping:
            break

        if page < maxPages - 1:
            # Snapshot last row icons before scrolling — faster overlap check than
            # OCR-peeking / reading-then-rolling-back the next page's first row.
            preScrollGrid = scroller._capture()
            tailStrips = [scroller._cellStrip(preScrollGrid, ROWS - 1, c) for c in range(COLS)]
            scroller._focusGrid()
            time.sleep(0.08)
            if not scroller.scrollPage():
                logger.info("Weapons: grid will not scroll further — done (%s collected)", len(weapons))
                break
            afterScroll = _gridFingerprint(scroller)
            if afterScroll == fingerprint:
                logger.warning(
                    "Weapons: scroll left grid unchanged — stopping to avoid re-scanning (%s collected)",
                    len(weapons),
                )
                break
            postScrollGrid = scroller._capture()
            iconMatches = sum(
                1 for c in range(COLS)
                if scroller._stripsMatch(tailStrips[c], scroller._cellStrip(postScrollGrid, 0, c), maxMeanDiff=12.0)
            )
            if iconMatches >= max(4, COLS - 1):
                logger.warning(
                    "Weapons: scroll left %s/%s last-row icons on top — nudging 1 row",
                    iconMatches, COLS,
                )
                scroller._focusGrid()
                if not scroller._scrollRows(1.0):
                    logger.info("Weapons: could not nudge past overlap — done (%s collected)", len(weapons))
                    break
                time.sleep(0.15)
                # Icon nudge already cleared overlap — skip OCR rollback on next page.
                prevTail = []

    del _cache
    logger.info("Weapons finished count=%s expected=%s", len(weapons), weaponCount)
    return inventory, weapons, weaponCount
