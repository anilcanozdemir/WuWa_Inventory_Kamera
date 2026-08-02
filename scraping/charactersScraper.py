import re
import time
import string
import logging
from collections import defaultdict

import cv2
from difflib import get_close_matches as getMatches

from scraping.utils import charactersID, characterAliases, weaponsID, definedText, echoesID
from scraping.utils import (
    screenshot, convertToBlackWhite, imageToString,
    WindowsInputController
)
from game.screenInfo import ScreenInfo
from game.menu import MainMenuController, normalizeMenuText
from properties.config import cfg

logger = logging.getLogger('CharacterScraper')

# Constants
SKILL_LEGENDS = {
    0: 'normal',
    1: 'resonance',
    2: 'forte',
    3: 'liberation',
    4: 'intro'
}
ASCENSION_LEVELS = [20, 40, 50, 60, 70, 80, 90]
LEVEL_PAIR_RE = re.compile(r'(\d{1,3})\s*/\s*(\d{1,3})')

# Full-roster detail scrapers — enabled after one-char smoke (Weapon/Forte/Chain/Echo).
# tools/scan_characters.py turns these on; START_ONE_CHAR.bat overrides per-call.
SCRAPE_WEAPON = True
SCRAPE_ECHOES = True
SCRAPE_SKILLS = True
SCRAPE_CHAIN = True

# Header OCR markers → tab name (first match wins).
# Live 1440p often drops the leading letter: Forte→orte, Echo→cho, Weapon→eapon.
_TAB_MARKERS = {
    'overview': ('overview', 'verview'),
    'weapon': ('weapon', 'eapon'),
    'echo': ('echo', 'cho'),
    'forte': ('forte', 'orte'),
    'chain': ('chain', 'resonanc', 'esonance'),
}


def parseLevelPair(text: str) -> tuple[int, int]:
    """Parse 'Lv. 80 / 80' (or OCR junk) into (level, ascensionCap)."""
    raw = text or ''
    # Prefer an explicit pair before falling back to digit soup.
    m = re.search(r'(\d{1,2})\s*/\s*(\d{1,2})', raw)
    if m:
        level, cap = int(m.group(1)), int(m.group(2))
        level = max(1, min(level, 90))
        if cap not in ASCENSION_LEVELS:
            cap = next((c for c in ASCENSION_LEVELS if c >= level), level)
        return level, ASCENSION_LEVELS.index(cap) if cap in ASCENSION_LEVELS else 0

    nums = [int(n) for n in re.findall(r'\d+', raw)]
    if not nums:
        return 1, 0

    # OCR glues "Lv.1/20"→"120", "70/70"→"7017V." / "7070".
    if len(nums) == 1 and nums[0] > 90:
        glued = str(nums[0])
        for cap in reversed(ASCENSION_LEVELS):
            cap_s = str(cap)
            if glued.endswith(cap_s) and len(glued) > len(cap_s):
                level_s = glued[:-len(cap_s)]
                if level_s.isdigit():
                    level = int(level_s)
                    if 1 <= level <= cap:
                        return level, ASCENSION_LEVELS.index(cap)
        if len(glued) == 4:
            level = int(glued[:2])
            if 1 <= level <= 90:
                cap = next((c for c in ASCENSION_LEVELS if c >= level), level)
                return level, ASCENSION_LEVELS.index(cap) if cap in ASCENSION_LEVELS else 0
        return 1, 0

    level = nums[0]
    cap = nums[1] if len(nums) > 1 else nums[0]

    # ".70V.170" → cap 170; prefer a known ascension cap appearing in the OCR.
    if cap not in ASCENSION_LEVELS:
        for c in ASCENSION_LEVELS:
            if c == level or str(c) in raw:
                cap = c
                break
        else:
            cap = next((c for c in ASCENSION_LEVELS if c >= level), 20)

    level = max(1, min(int(level), 90))
    try:
        ascension = ASCENSION_LEVELS.index(cap)
    except ValueError:
        ascension = 0
    return level, ascension


def _resonatorHeaderText(screenInfo: ScreenInfo) -> str:
    """OCR the top-left tab/header strip used by Resonator screens."""
    x = max(0, int(screenInfo.terminal.x) - 20)
    y = max(0, int(screenInfo.terminal.y) - 10)
    w = int(screenInfo.terminal.w) + 80
    h = int(screenInfo.terminal.h) + 40
    image = screenshot(x, y, w, h, screenInfo.monitor)
    text = normalizeMenuText(imageToString(image, ''))
    text_bw = normalizeMenuText(imageToString(convertToBlackWhite(image), ''))
    return text + text_bw


def isOnResonatorOverview(screenInfo: ScreenInfo) -> bool:
    """True when top-left header looks like Overview (not Terminal / gameplay)."""
    combined = _resonatorHeaderText(screenInfo)
    ok = 'overview' in combined or 'verview' in combined
    logger.debug("Resonator overview OCR=%r ok=%s", combined, ok)
    return ok


def isOnResonatorScreen(screenInfo: ScreenInfo) -> bool:
    """
    True on any Resonator tab (Overview / Weapon / Echo / Forte / Chain).

    Pressing C while already here closes the menu — scrapers must click Overview
    instead of toggling the hotkey.
    """
    combined = _resonatorHeaderText(screenInfo)
    markers = (
        'overview', 'verview',
        'echo', 'cho',
        'weapon', 'eapon',
        'forte', 'orte',
        'skill',  # "Inherent Skill" popup
        'inherent',
        'stat', 'bonus',  # "Stat Bonus" node popup
        'chain', 'resonanc', 'esonance',
        'activated',
    )
    ok = any(m in combined for m in markers)
    if ok:
        logger.debug("Resonator screen OCR=%r ok=%s", combined, ok)
        return True

    # Fallback: name ROI readable (custom names like "Luuk Hersson" on Echo tab).
    nameBox = screenInfo.characters.resonatorName
    nameImg = screenshot(
        nameBox.x, nameBox.y, nameBox.w, nameBox.h, screenInfo.monitor,
    )
    name = re.sub(r'[^a-z0-9]', '', imageToString(nameImg, '', bannedChars=' ').lower())
    if len(name) < 3:
        name = re.sub(
            r'[^a-z0-9]',
            '',
            imageToString(convertToBlackWhite(nameImg), '', bannedChars=' ').lower(),
        )
    ok = len(name) >= 3
    logger.debug("Resonator screen OCR=%r name=%r ok=%s", combined, name, ok)
    return ok


def ensureResonatorOverview(controller: WindowsInputController, screenInfo: ScreenInfo) -> bool:
    """Click the left Overview tab if we are on another Resonator tab."""
    if isOnResonatorOverview(screenInfo):
        return True
    clickResonatorTab(controller, screenInfo, 'overview')
    time.sleep(0.45)
    if isOnResonatorOverview(screenInfo):
        return True
    # Header OCR can miss; accept if name ROI still looks like a resonator card.
    return isOnResonatorScreen(screenInfo)


def _tabClickPoint(screenInfo: ScreenInfo, tab: str) -> tuple[int, int] | None:
    """Return (x,y) for a named tab from explicit coords or strip index."""
    attrs = {
        'overview': 'tabOverview',
        'weapon': 'tabWeapon',
        'echo': 'tabEcho',
        'forte': 'tabForte',
        'chain': 'tabChain',
    }
    attr = attrs.get(tab)
    if attr and hasattr(screenInfo.characters, attr):
        pt = getattr(screenInfo.characters, attr)
        return int(pt.x), int(pt.y)
    if tab == 'overview':
        return int(screenInfo.characters.leftSide.x), int(screenInfo.characters.leftSide.y)
    return None


def _headerMatchesTab(combined: str, tab: str) -> bool:
    markers = _TAB_MARKERS.get(tab, ())
    return any(m in combined for m in markers)


def discoverResonatorTabs(
    controller: WindowsInputController,
    screenInfo: ScreenInfo,
) -> dict[str, tuple[int, int]]:
    """
    Click each left-strip candidate and map header OCR → tab name.
    Returns {tabName: (x,y)}. Always ends on Overview when possible.
    """
    x = int(screenInfo.characters.leftSide.x)
    ys = list(getattr(screenInfo.characters, 'tabStripYs', None) or [])
    if not ys:
        y0 = int(screenInfo.characters.leftSide.y)
        step = int(getattr(screenInfo.characters.offsets.leftSide, 'y', 180) or 180)
        ys = [y0 + step * i for i in range(5)]

    mapping: dict[str, tuple[int, int]] = {}
    for y in ys:
        controller.leftClick(x, int(y), 0.35)
        time.sleep(0.5)
        combined = _resonatorHeaderText(screenInfo)
        for tab, markers in _TAB_MARKERS.items():
            if tab in mapping:
                continue
            if any(m in combined for m in markers):
                mapping[tab] = (x, int(y))
                logger.info("Tab discover %s → (%s,%s) header=%r", tab, x, y, combined[:80])
                break
        else:
            logger.debug("Tab strip y=%s unmatched header=%r", y, combined[:80])

    for tab in _TAB_MARKERS:
        if tab not in mapping:
            pt = _tabClickPoint(screenInfo, tab)
            if pt:
                mapping[tab] = pt
                logger.info("Tab fallback %s → %s", tab, pt)

    clickResonatorTab(controller, screenInfo, 'overview', tabMap=mapping)
    return mapping


def clickResonatorTab(
    controller: WindowsInputController,
    screenInfo: ScreenInfo,
    tab: str,
    tabMap: dict[str, tuple[int, int]] | None = None,
    *,
    verify: bool = True,
) -> bool:
    """Click a resonator left-rail tab. Optionally verify via header OCR."""
    pt = None
    if tabMap and tab in tabMap:
        pt = tabMap[tab]
    if pt is None:
        pt = _tabClickPoint(screenInfo, tab)
    if pt is None:
        logger.error("No click point for resonator tab %r", tab)
        return False

    controller.leftClick(pt[0], pt[1], 0.35)
    time.sleep(0.5)
    if not verify:
        return True

    combined = _resonatorHeaderText(screenInfo)
    if _headerMatchesTab(combined, tab):
        return True

    fallback = _tabClickPoint(screenInfo, tab)
    if fallback and fallback != pt:
        controller.leftClick(fallback[0], fallback[1], 0.35)
        time.sleep(0.5)
        combined = _resonatorHeaderText(screenInfo)
        if _headerMatchesTab(combined, tab):
            return True

    logger.warning("Tab %s verify failed header=%r", tab, combined[:100])
    return False


def scrapeResonator(image, screenInfo: ScreenInfo, characters: dict, _cache: dict) -> tuple[str | None, bool]:
    """
    Read Overview name + level.

    Returns (resonatorID, stopScanning).
    stopScanning is True only when we hit a *valid* character already scanned
    (end of the roster). Empty/failed OCR never stops the scan.
    """
    nameBox = screenInfo.characters.resonatorName
    levelBox = screenInfo.characters.resonatorLevel

    resonatorNameImage = image[
        nameBox.y:nameBox.y + nameBox.h,
        nameBox.x:nameBox.x + nameBox.w,
    ]
    # Prefer color OCR — B&W preprocessing mangles "Luuk Herssen" / "Lv. 80 / 80".
    resonatorNameHash = hash(resonatorNameImage.tobytes())

    if resonatorNameHash in _cache:
        cached = _cache[resonatorNameHash]
        if cached and cached in characters:
            return cached, True
        resonatorID = cached
    else:
        def _cleanName(raw: str) -> str:
            return re.sub(r'[^a-z0-9]', '', (raw or '').lower())

        def _resolveName(raw: str) -> str | None:
            name = _cleanName(raw)
            if not name:
                return None
            alias = characterAliases.get(name)
            if not alias:
                aliasHit = getMatches(name, list(characterAliases), 1, 0.8)
                if aliasHit:
                    alias = characterAliases[aliasHit[0]]
            if alias:
                return alias
            hit = getMatches(name, list(charactersID), 1, 0.75)
            return hit[0] if hit else (name if name in charactersID else None)

        rover = re.sub(r'[^a-z0-9]', '', cfg.get(cfg.roverName).replace(' ', '').lower())

        def _tryResolve(img) -> tuple[str | None, str]:
            raw = imageToString(img, '', bannedChars=' ')
            cleaned = _cleanName(raw)
            resolved = _resolveName(raw)
            if not resolved and cleaned == rover:
                resolved = rover
            # Aalto: double-A often collapses to junk; accept aa*t* shapes.
            if not resolved and cleaned.startswith('aa') and 't' in cleaned:
                resolved = 'aalto'
            return resolved, cleaned

        resolved, resonatorName = _tryResolve(resonatorNameImage)
        if not resolved:
            # One upscale retry only — Aalto/Jianxin fail at native scale.
            up = cv2.resize(resonatorNameImage, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            resolved, alt = _tryResolve(up)
            if alt:
                resonatorName = alt
        if not resolved:
            up3 = cv2.resize(resonatorNameImage, None, fx=3.0, fy=3.0, interpolation=cv2.INTER_CUBIC)
            resolved, alt = _tryResolve(up3)
            if alt:
                resonatorName = alt
        if not resolved and len(resonatorName) < 2:
            resolved, alt = _tryResolve(convertToBlackWhite(resonatorNameImage))
            if alt:
                resonatorName = alt

        logger.debug("Resonator name OCR=%r resolved=%r", resonatorName, resolved)

        if not resolved:
            if len(resonatorName) < 4:
                _cache[resonatorNameHash] = None
                return None, False
            logger.warning("Unrecognized resonator OCR=%r — add alias if renamed", resonatorName)
            _cache[resonatorNameHash] = None
            return None, False

        resonatorName = resolved
        resonatorID = '1502' if resonatorName == rover else charactersID.get(resonatorName)
        if not resonatorID:
            logger.warning("Unrecognized resonator OCR=%r — add alias if renamed", resonatorName)
            _cache[resonatorNameHash] = None
            return None, False
        _cache[resonatorNameHash] = resonatorID

    if not resonatorID:
        return None, False

    if resonatorID in characters:
        return resonatorID, True

    levelImage = image[
        levelBox.y:levelBox.y + levelBox.h,
        levelBox.x:levelBox.x + levelBox.w,
    ]
    levelHash = hash(levelImage.tobytes())

    if levelHash in _cache:
        levelText = _cache[levelHash]
    else:
        levelText = imageToString(levelImage, '')
        if not re.search(r'\d', levelText or ''):
            levelText = imageToString(convertToBlackWhite(levelImage), '')
        _cache[levelHash] = levelText
    logger.debug("Resonator level OCR=%r", levelText)

    characterLvl, ascensionLvl = parseLevelPair(levelText)
    characters[resonatorID]['level'] = characterLvl
    characters[resonatorID]['ascension'] = ascensionLvl
    logger.info(
        "Scraped resonator id=%s level=%s ascension=%s",
        resonatorID, characterLvl, ascensionLvl,
    )
    return resonatorID, False


def _ocrLevelPairCrop(crop) -> str:
    """Inventory-style level OCR: B&W + digits/'/' → 'curr/max' or ''."""
    if crop is None or getattr(crop, 'size', 0) == 0:
        return ''

    def _parse(raw: str) -> str:
        match = LEVEL_PAIR_RE.search(raw or '')
        if not match:
            return ''
        curr, mx = int(match.group(1)), int(match.group(2))
        if 1 <= curr <= 90 and curr <= mx <= 90:
            return f'{curr}/{mx}'
        return ''

    # Upscale thin bands (same trick as weapon name).
    big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    bw = convertToBlackWhite(big)
    text = _parse(imageToString(bw, '', allowedChars=string.digits + '/'))
    if not text:
        text = _parse(imageToString(bw, ''))
    if not text:
        text = _parse(imageToString(big, '', allowedChars=string.digits + '/'))
    if not text:
        text = _parse(imageToString(big, ''))
    return text


def _readEquippedWeaponLevel(image, screenInfo: ScreenInfo) -> str:
    """
    Read equipped-weapon Level N/N on the Resonator Weapon tab.
    Same OCR strategy as weapons inventory (_readWeaponLevel): B&W first,
    digit pair only, then a wider / under-name fallback so 'Level 80/80' isn't clipped.
    """
    box = screenInfo.characters.weaponLevel
    candidates = [
        image[int(box.y):int(box.y + box.h), int(box.x):int(box.x + box.w)],
        # Wider band — inventory needs ~360px for "Level 80/80".
        image[
            int(box.y - 8):int(box.y + box.h + 12),
            int(box.x):int(box.x + max(box.w, 360)),
        ],
    ]
    name = screenInfo.characters.weaponName
    # Band just under the name (UI puts Level on the next line).
    under_y = int(name.y + name.h)
    candidates.append(
        image[under_y:under_y + 70, int(name.x):int(name.x + max(name.w, 360))]
    )

    for crop in candidates:
        text = _ocrLevelPairCrop(crop)
        if text:
            return text
    return ''


def scrapeWeapon(image, screenInfo: ScreenInfo, characters: dict, resonatorID: str, _cache: dict):
    """Weapon OCR from the already-open Weapon tab screenshot."""
    nameBox = screenInfo.characters.weaponName
    weaponNameImage = image[
        nameBox.y:nameBox.y + nameBox.h,
        nameBox.x:nameBox.x + nameBox.w,
    ]
    weaponNameHash = hash(weaponNameImage.tobytes())
    if weaponNameHash in _cache:
        weaponID = _cache[weaponNameHash]
    else:
        # Color first — B&W mangles apostrophes (Daybreaker's Spine).
        big = cv2.resize(weaponNameImage, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        weaponName = imageToString(big, '', bannedChars=' ').lower()
        weaponName = re.sub(r'[^a-z0-9]', '', weaponName)
        if len(weaponName) < 3:
            weaponName = re.sub(
                r'[^a-z0-9]',
                '',
                imageToString(convertToBlackWhite(big), '', bannedChars=' ').lower(),
            )
        result = getMatches(weaponName, list(weaponsID.keys()), 1, 0.65)
        if result:
            weaponName = result[0]
        entry = weaponsID.get(weaponName)
        weaponID = entry['id'] if isinstance(entry, dict) else (entry or weaponName)
        _cache[weaponNameHash] = weaponID
        logger.debug("Weapon OCR name=%r id=%s", weaponName, weaponID)

    levelText = _readEquippedWeaponLevel(image, screenInfo)
    logger.debug("Weapon OCR level=%r", levelText)

    rankBox = screenInfo.characters.weaponRank
    rankImage = image[
        rankBox.y:rankBox.y + rankBox.h,
        rankBox.x:rankBox.x + rankBox.w,
    ]
    rankBig = cv2.resize(rankImage, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    rank = imageToString(rankBig, '', allowedChars=string.digits)
    if not rank:
        rank = imageToString(convertToBlackWhite(rankBig), '', allowedChars=string.digits)

    try:
        level, ascension = parseLevelPair(levelText) if levelText else (1, 0)
        characters[resonatorID]['weapon']['id'] = weaponID
        characters[resonatorID]['weapon']['level'] = level
        characters[resonatorID]['weapon']['ascension'] = ascension
        characters[resonatorID]['weapon']['rank'] = int(rank or 1)
        logger.info(
            "Scraped weapon id=%s level=%s/%s rank=%s",
            weaponID, level, ASCENSION_LEVELS[ascension] if 0 <= ascension < len(ASCENSION_LEVELS) else '?',
            characters[resonatorID]['weapon']['rank'],
        )
    except Exception:
        logger.debug('Failed scraping the weapon', exc_info=True)


def _statusIsActivated(text: str) -> bool | None:
    """
    True  = node/chain already owned ("Activated")
    False = locked / can-unlock panel ("Activate", upgrade/cost, etc.)
    None  = inconclusive OCR
    """
    t = (text or '').lower()
    if not t.strip():
        return None
    compact = re.sub(r'[^a-z]', '', t)
    # Owned status (past tense). Bare "Activate" on locked nodes must NOT count —
    # older `'activat' in text` false-positived every unbought node.
    if re.search(r'\bactivated\b', t) or 'activated' in compact:
        return True
    if re.search(r'\bactivate\b', t) or 'activate' in compact:
        return False
    if any(k in t for k in ('upgrade', 'ascension', 'rank', 'available', 'shell', 'cost', 'prerequisite')):
        return False
    return None


def _ocrActivatedButton(screenInfo: ScreenInfo) -> tuple[bool, str]:
    """
    Upstream: OCR skillButton / chainButton for definedText['Activated'].
    1440p left-panel bottom moves; try configured ROI plus a few nearby boxes.
    """
    base = screenInfo.characters.skillButton
    chain = getattr(screenInfo.characters, 'chainButton', None)
    boxes = [
        base,
        chain,
        type(base)(180, 1180, 420, 120),
        type(base)(150, 1100, 500, 180),
        type(base)(200, 1280, 360, 80),
        type(base)(267, 1307, 160, 47),  # scaled upstream
        type(base)(400, 1260, 220, 80),
    ]
    best_neg = ''
    for box in boxes:
        if box is None:
            continue
        x, y, w, h = int(box.x), int(box.y), int(box.w), int(box.h)
        if w <= 0 or h <= 0:
            continue
        if y + h > screenInfo.height or x + w > screenInfo.width:
            continue
        img = screenshot(x, y, w, h, monitor=screenInfo.monitor)
        for variant in (
            img,
            convertToBlackWhite(img) if img.ndim == 3 else img,
            cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC),
        ):
            text = imageToString(variant, '').lower()
            if not text:
                continue
            verdict = _statusIsActivated(text)
            if verdict is True:
                return True, text
            if verdict is False:
                return False, text
            best_neg = best_neg or text
    return False, best_neg


def scrapeSkills(
    controller: WindowsInputController,
    screenInfo: ScreenInfo,
    characters: dict,
    resonatorID: str,
    _cache: dict,
    tabMap: dict | None = None,
) -> bool:
    """
    Upstream Psycho-Marcus skill + node scrape:

      click skill → OCR level
      for up to 2 nodes above: click → if button == Activated → stats/inherent += 1 else stop
      Esc

    Nodes can be flat/% stat bonuses (stats0/1/3/4) or inherent (forte column).
    Active vs inactive is the Activated label — same as upstream.
    """
    del tabMap

    node_offsets = list(getattr(screenInfo.characters, 'skillNodeOffsets', None) or [])
    fallback_dy = int(getattr(screenInfo.characters.offsets.skillPosition, 'y', 350) or 350)

    def _panelOpen() -> bool:
        header = _resonatorHeaderText(screenInfo)
        if any(m in header for m in ('circuit', 'inherent', 'stat', 'bonus', 'activated', 'attack', 'liberation', 'intro')):
            return True
        if 'resonance' in header and 'chain' not in header:
            return True
        if ('orte' in header or 'forte' in header) and len(header) > 12:
            return True
        return False

    def _dismissPanel() -> None:
        if _panelOpen():
            controller.pressKey('esc', 0.2)
            time.sleep(0.35)
        if _panelOpen():
            _leftRailClick(controller, screenInfo, 3)

    for index, skills in enumerate(screenInfo.characters.skillPositions):
        if not isOnResonatorScreen(screenInfo):
            logger.error("Left Resonator before skill %s — abort", index)
            return False

        # Outer skills sit on a lower arc — single click often misses. Probe nearby.
        click_offsets = [(0, 0)]
        if index == 0:  # Normal Attack
            click_offsets = [
                (0, 0), (40, -40), (-20, -50), (60, -25), (0, -70), (80, -50), (-40, -30),
            ]
        elif index == 4:  # Intro Skill
            click_offsets = [
                (0, 0), (-40, -40), (20, -50), (-60, -25), (0, -70), (-80, -50), (40, -30),
            ]

        level = 1
        hit_x, hit_y = int(skills.x), int(skills.y)
        opened = False
        for dx, dy in click_offsets:
            cx, cy = int(skills.x + dx), int(skills.y + dy)
            controller.leftClick(cx, cy, 0.4)
            time.sleep(0.7)

            image = screenshot(
                width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor,
            )
            levelBox = screenInfo.characters.skillLevel
            levelImage = image[
                levelBox.y:levelBox.y + levelBox.h,
                levelBox.x:levelBox.x + levelBox.w,
            ]
            levelBig = cv2.resize(levelImage, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            levelTxt = imageToString(levelBig, '', allowedChars=string.digits)
            if not levelTxt:
                levelTxt = imageToString(convertToBlackWhite(levelBig), '', allowedChars=string.digits)
            if not levelTxt:
                raw = imageToString(levelBig, '') + imageToString(convertToBlackWhite(levelBig), '')
                m = re.search(r'(\d{1,2})', raw or '')
                levelTxt = m.group(1) if m else ''
            try:
                cand = int(levelTxt)
                if 1 <= cand <= 10:
                    level = cand
            except Exception:
                pass

            opened = _panelOpen()
            logger.debug(
                "Skill %s try @(%s,%s) level=%s panel=%s",
                index, cx, cy, level, opened,
            )
            # Success: panel open, or we clearly read a real level for non-intro.
            if opened or (index != 4 and level >= 2) or (index == 0 and level >= 2):
                hit_x, hit_y = cx, cy
                break
            _dismissPanel()

        characters[resonatorID]['skills'][SKILL_LEGENDS[index]] = int(level)
        logger.debug(
            "Skill %s (%s) hit @(%s,%s) level=%s",
            index, SKILL_LEGENDS[index], hit_x, hit_y, level,
        )

        # Close skill panel so node clicks use stable overview coordinates.
        _dismissPanel()
        if not isOnResonatorScreen(screenInfo):
            logger.error("Left Resonator after skill %s panel — abort", index)
            return False

        # --- nodes above skill (flat/% stats or inherent) ---
        # Prefer absolute recorded node clicks (overview tree); else Y-offsets.
        node_groups = list(getattr(screenInfo.characters, 'skillNodes', None) or [])
        if index < len(node_groups) and node_groups[index]:
            node_points = [(int(n.x), int(n.y)) for n in node_groups[index]]
        else:
            deltas = node_offsets[index] if index < len(node_offsets) else [fallback_dy, fallback_dy * 2]
            node_points = [(hit_x, int(hit_y - int(dy))) for dy in deltas]

        for n, (nx, ny) in enumerate(node_points, start=1):
            controller.leftClick(nx, ny, 0.55)
            time.sleep(0.45)

            is_on, button = _ocrActivatedButton(screenInfo)
            logger.debug(
                "Skill %s node %s @(%s,%s) activated=%s button=%r",
                index, n, nx, ny, is_on, button,
            )

            if is_on:
                key = 'inherent' if index == 2 else f'stats{index}'
                characters[resonatorID]['skills'][key] += 1
                _dismissPanel()
            else:
                _dismissPanel()
                break

        if not isOnResonatorScreen(screenInfo):
            logger.error("Left Resonator during skills (skill %s) — abort", index)
            return False

    logger.info(
        "Scraped skills for %s: liberation=%s inherent=%s stats0=%s stats1=%s stats3=%s stats4=%s",
        resonatorID,
        characters[resonatorID]['skills']['liberation'],
        characters[resonatorID]['skills']['inherent'],
        characters[resonatorID]['skills']['stats0'],
        characters[resonatorID]['skills']['stats1'],
        characters[resonatorID]['skills']['stats3'],
        characters[resonatorID]['skills']['stats4'],
    )
    return True


def scrapeChain(
    controller: WindowsInputController,
    screenInfo: ScreenInfo,
    characters: dict,
    resonatorID: str,
    _cache: dict,
    tabMap: dict | None = None,
) -> bool:
    """Click each Sequence node, OCR Activated, Esc to close the detail panel."""
    del tabMap, _cache

    def _dismissChainPanel() -> bool:
        """Esc after a node click. Returns False if we left Resonators."""
        controller.pressKey('esc', 0.2)
        time.sleep(0.35)
        if not isOnResonatorScreen(screenInfo):
            logger.error("Left Resonator after Chain Esc — abort")
            return False
        return True

    characters[resonatorID]['chain'] = 0
    for i, position in enumerate(screenInfo.characters.chainPositions):
        controller.leftClick(position.x, position.y, 0.25)
        time.sleep(0.45)

        is_on, button = _ocrActivatedButton(screenInfo)
        logger.debug(
            "Chain node %s @(%s,%s) activated=%s button=%r",
            i + 1, position.x, position.y, is_on, button,
        )

        # Detail panel stays open until Esc — next node is otherwise unclickable.
        if not _dismissChainPanel():
            return False

        if not is_on:
            break
        characters[resonatorID]['chain'] += 1

    logger.info("Scraped chain=%s for %s", characters[resonatorID]['chain'], resonatorID)
    return True


def _leftRailClick(
    controller: WindowsInputController,
    screenInfo: ScreenInfo,
    section: int,
) -> None:
    """Upstream: leftClick(leftSide.x, leftSide.y + offset*section)."""
    x = int(screenInfo.characters.leftSide.x)
    # Prefer calibrated tab Y list when present (1440p), else offset math.
    ys = list(getattr(screenInfo.characters, 'tabStripYs', None) or [])
    if ys and 0 <= section < len(ys):
        y = int(ys[section])
    else:
        y = int(screenInfo.characters.leftSide.y + screenInfo.characters.offsets.leftSide.y * section)
    controller.leftClick(x, y, 0.8)
    time.sleep(0.35)


def scrapeCharacterDetails(
    controller: WindowsInputController,
    screenInfo: ScreenInfo,
    characters: dict,
    resonatorID: str,
    _cache: dict,
    tabMap: dict | None = None,
    *,
    do_weapon: bool | None = None,
    do_skills: bool | None = None,
    do_chain: bool | None = None,
    do_echoes: bool | None = None,
):
    """
    Match upstream Psycho-Marcus resonator section loop:

      for section in 0..4:
          click left rail section
          0=name/level (caller already did), 1=weapon, 2=echo, 3=skills, 4=chain

    No tab-discover, no Overview bounce between sections, no re-clicking Weapon.
    """
    del tabMap
    weapon = SCRAPE_WEAPON if do_weapon is None else do_weapon
    skills = SCRAPE_SKILLS if do_skills is None else do_skills
    chain = SCRAPE_CHAIN if do_chain is None else do_chain
    echoes = SCRAPE_ECHOES if do_echoes is None else do_echoes
    if not any((weapon, skills, chain, echoes)):
        return

    # section 1 — Weapon (exactly once)
    if weapon:
        _leftRailClick(controller, screenInfo, 1)
        time.sleep(0.45)  # let weapon card settle
        image = screenshot(
            width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor,
        )
        scrapeWeapon(image, screenInfo, characters, resonatorID, _cache)
        if not isOnResonatorScreen(screenInfo):
            logger.error("Left Resonator after weapon — abort details")
            return

    # section 2 — Echoes (optional; upstream skips)
    if echoes:
        _leftRailClick(controller, screenInfo, 2)
        scrapeEquippedEchoes(controller, screenInfo, characters, resonatorID, _cache, tabMap=None)
        if not isOnResonatorScreen(screenInfo):
            logger.error("Left Resonator after echoes — abort details")
            return

    # section 3 — Forte / skills
    if skills:
        _leftRailClick(controller, screenInfo, 3)
        if not scrapeSkills(controller, screenInfo, characters, resonatorID, _cache):
            logger.error("Skills aborted — skipping remaining details for %s", resonatorID)
            return

    # section 4 — Resonance Chain
    if chain:
        _leftRailClick(controller, screenInfo, 4)
        if not scrapeChain(controller, screenInfo, characters, resonatorID, _cache):
            logger.error("Chain aborted for %s", resonatorID)
            return

    # Land back on Overview once at the end (does not re-open Weapon).
    if isOnResonatorScreen(screenInfo):
        _leftRailClick(controller, screenInfo, 0)


def scrapeEquippedEchoes(
    controller: WindowsInputController,
    screenInfo: ScreenInfo,
    characters: dict,
    resonatorID: str,
    _cache: dict,
    tabMap: dict | None = None,
):
    """
    Read equipped echoes from the Echo equip/switch UI.

    Flow (no Esc between slots):
      1. On Resonator Echo overview, click echoEnterClick (or first overview slot)
         → opens the equip screen (left = 5 equipped, right = detail).
      2. Click each left-rail equipped slot; OCR name / +level / sonata from the right panel.
      3. Esc once to return to Resonator Echo tab (needed before Forte/Chain).
    """
    del tabMap
    slots = list(getattr(screenInfo.characters, 'echoSlotPositions', []) or [])
    nameBox = getattr(screenInfo.characters, 'echoDetailName', None)
    levelBox = getattr(screenInfo.characters, 'echoDetailLevel', None)
    sonataBox = getattr(screenInfo.characters, 'echoSonataIcon', None)
    enter = getattr(screenInfo.characters, 'echoEnterClick', None)
    if not slots or nameBox is None:
        logger.warning("Echo slot ROIs missing — skip")
        return

    findSonata = None
    sonataFromText = None
    processStatsFn = None
    try:
        from scraping.echoesScraper import findSonataNearPoint as findSonata
        from scraping.echoesScraper import matchSonataByText as sonataFromText
        from scraping.echoesScraper import processStats as processStatsFn
    except Exception:
        logger.debug("Echo helpers unavailable", exc_info=True)

    statsNameBox = getattr(screenInfo.characters, 'echoFullStatsName', None)
    statsValueBox = getattr(screenInfo.characters, 'echoFullStatsValue', None)
    sonataTextBox = getattr(screenInfo.characters, 'echoSonataText', None)
    overviewSonataBox = getattr(screenInfo.characters, 'echoOverviewSonata', None)

    def _sonataOcr(img, boxes) -> str:
        if sonataFromText is None:
            return ''
        for box in boxes:
            if box is None or not getattr(box, 'w', 0):
                continue
            crop = img[
                int(box.y):int(min(screenInfo.height, box.y + box.h)),
                int(box.x):int(min(screenInfo.width, box.x + box.w)),
            ]
            if crop.size == 0:
                continue
            big = cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            raw = imageToString(big, '').lower()
            if not raw:
                raw = imageToString(convertToBlackWhite(big), '').lower()
            hit = sonataFromText(raw)
            if hit:
                logger.debug("Sonata OCR hit=%r from %r", hit, raw[:100])
                return hit
        return ''

    # Read set name from Echo overview BEFORE opening the equip UI.
    overviewSonata = ''
    pre = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
    overviewSonata = _sonataOcr(
        pre,
        [
            overviewSonataBox,
            type(nameBox)(180, 920, 600, 280),
            type(nameBox)(200, 850, 550, 350),
        ],
    )
    if overviewSonata:
        logger.info("Echo overview sonata=%s", overviewSonata)

    # Enter equip UI once (overview arc → left-rail slots become available).
    if enter is not None:
        controller.leftClick(enter.x, enter.y, 0.35)
    else:
        controller.leftClick(slots[0].x, slots[0].y, 0.35)
    time.sleep(0.55)

    def _nameRoiHash(img) -> int:
        crop = img[
            int(nameBox.y):int(nameBox.y + nameBox.h),
            int(nameBox.x):int(nameBox.x + nameBox.w),
        ]
        return hash(crop.tobytes()) if crop.size else 0

    equipped = {}
    stale_streak = 0
    seen_fps: set[tuple] = set()
    for idx, slot in enumerate(slots):
        before = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
        before_hash = _nameRoiHash(before)

        controller.leftClick(slot.x, slot.y, 0.3)
        time.sleep(0.45)
        image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
        after_hash = _nameRoiHash(image)

        # Empty equipped slot: right panel keeps the previous/bag selection.
        if after_hash == before_hash:
            stale_streak += 1
            logger.debug(
                "Echo slot %s — detail panel unchanged (empty slot)", idx,
            )
            # A run of empties → remaining left-rail slots are empty too.
            if stale_streak >= 2:
                logger.info("Echo slots %s+ empty — stop clicking", idx)
                break
            continue
        stale_streak = 0

        nameImg = image[nameBox.y:nameBox.y + nameBox.h, nameBox.x:nameBox.x + nameBox.w]
        big = cv2.resize(nameImg, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        raw = imageToString(big, '', bannedChars=' ').lower()
        name = re.sub(r'[^a-z0-9]', '', raw)
        if len(name) < 3:
            name = re.sub(
                r'[^a-z0-9]',
                '',
                imageToString(convertToBlackWhite(big), '', bannedChars=' ').lower(),
            )
        if len(name) < 3:
            logger.debug("Echo slot %s — empty name OCR=%r", idx, raw)
            continue

        level = 0
        if levelBox is not None:
            lvlImg = image[levelBox.y:levelBox.y + levelBox.h, levelBox.x:levelBox.x + levelBox.w]
            lvlBig = cv2.resize(lvlImg, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
            lvlCandidates = [
                imageToString(lvlBig, '', allowedChars=string.digits + '+'),
                imageToString(convertToBlackWhite(lvlBig), '', allowedChars=string.digits + '+'),
                imageToString(lvlBig, ''),
            ]
            # Fallback: +N often sits on the same header row as the name.
            header = image[
                int(nameBox.y - 4):int(nameBox.y + nameBox.h + 8),
                int(nameBox.x):int(min(screenInfo.width, nameBox.x + nameBox.w + 160)),
            ]
            if header.size:
                hdrBig = cv2.resize(header, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                lvlCandidates.append(imageToString(hdrBig, '', allowedChars=string.digits + '+'))
            for lvlTxt in lvlCandidates:
                m = re.search(r'\+?\s*(\d{1,2})', lvlTxt or '')
                if not m:
                    continue
                value = int(m.group(1))
                if 0 <= value <= 25:
                    level = value
                    break
            logger.debug("Echo slot %s level OCR candidates=%r → %s", idx, lvlCandidates, level)

        sonata = ''
        # 1) Slide-match the yellow set badge on the left-rail portrait.
        if findSonata is not None:
            hit, score = findSonata(image, int(slot.x), int(slot.y), minScore=0.72)
            if hit:
                sonata = hit
            logger.debug("Echo slot %s sonata icon=%r score=%.3f", idx, hit, score)
        # 2) OCR fallback on equip right panel (skill / set lines).
        if not sonata:
            sonata = _sonataOcr(
                image,
                [
                    sonataTextBox,
                    type(nameBox)(1980, 750, 520, 450),
                    type(nameBox)(1980, 1080, 520, 160),
                ],
            )
            if sonata:
                logger.debug("Echo slot %s sonata OCR=%r", idx, sonata)
        # 3) Overview set name (same 5pc build → all slots share it).
        if not sonata and overviewSonata:
            sonata = overviewSonata

        tuneLv = 0
        stats: dict = {}
        if processStatsFn is not None and statsNameBox is not None and statsValueBox is not None:
            try:
                # Slot-0 debug crops help calibrate name/value columns.
                if idx == 0:
                    try:
                        from pathlib import Path
                        dbg = Path(__file__).resolve().parents[1] / 'debug_out' / '_echo_stats_crops'
                        dbg.mkdir(parents=True, exist_ok=True)
                        n = image[
                            int(statsNameBox.y):int(statsNameBox.y + statsNameBox.h),
                            int(statsNameBox.x):int(statsNameBox.x + statsNameBox.w),
                        ]
                        v = image[
                            int(statsValueBox.y):int(statsValueBox.y + statsValueBox.h),
                            int(statsValueBox.x):int(statsValueBox.x + statsValueBox.w),
                        ]
                        if n.size:
                            cv2.imwrite(str(dbg / 'names.png'), cv2.cvtColor(n, cv2.COLOR_RGB2BGR))
                        if v.size:
                            cv2.imwrite(str(dbg / 'values.png'), cv2.cvtColor(v, cv2.COLOR_RGB2BGR))
                    except Exception:
                        pass
                tuneLv, stats = processStatsFn(
                    image, screenInfo, _cache,
                    nameRoi=statsNameBox, valueRoi=statsValueBox,
                )
            except Exception:
                logger.debug("Echo slot %s stats OCR failed", idx, exc_info=True)

        try:
            hit = getMatches(name, list(echoesID), 1, 0.75)
            echoKey = hit[0] if hit else name
            echoId = str(echoesID.get(echoKey, echoKey))
        except Exception:
            echoKey = name
            echoId = name

        entry = {
            'id': echoId,
            'level': level,
            'name': echoKey,
            'tuneLv': tuneLv,
            'stats': stats,
        }
        if sonata:
            entry['sonata'] = sonata

        # Safety net: empty slots re-read the bag/previous panel as identical copies
        # (export showed 5× Hyvatia CD44 on characters with no echoes).
        fp = (
            str(echoId),
            int(level),
            repr((stats or {}).get('main')),
            repr((stats or {}).get('sub')),
        )
        if fp in seen_fps:
            logger.debug("Echo slot %s duplicate fingerprint %s — skip", idx, echoKey)
            stale_streak += 1
            if stale_streak >= 2:
                break
            continue
        seen_fps.add(fp)
        stale_streak = 0

        equipped[str(idx)] = entry
        logger.debug(
            "Echo slot %s → %s lvl=%s sonata=%r main=%s sub=%s",
            idx, echoId, level, sonata,
            (stats or {}).get('main'), (stats or {}).get('sub'),
        )

    # If some slots got a set name and others didn't, fill empties with the
    # dominant / overview sonata (typical 5pc mono-set builds).
    found = [e.get('sonata') for e in equipped.values() if e.get('sonata')]
    fill = overviewSonata
    if found:
        from collections import Counter
        fill = Counter(found).most_common(1)[0][0]
    if fill:
        for e in equipped.values():
            if not e.get('sonata'):
                e['sonata'] = fill

    # Back to Resonator Echo tab so Forte/Chain left-rail clicks still work.
    controller.pressKey('esc', 0.25)
    time.sleep(0.35)

    characters[resonatorID]['echoes'] = equipped
    logger.info("Scraped %s equipped echoes for %s", len(equipped), resonatorID)


def _emptyCharacters():
    return defaultdict(
        lambda: defaultdict(
            int,
            {
                'level': 0,
                'ascension': 0,
                'weapon': defaultdict(
                    int,
                    {
                        'id': 0,
                        'level': 1,
                        'ascension': 0,
                        'rank': 0
                    }
                ),
                'echoes': dict(),
                'skills': defaultdict(
                    int,
                    {
                        'normal': 1,
                        'resonance': 1,
                        'forte': 1,
                        'liberation': 1,
                        'intro': 1,
                        'stats0': 0,
                        'stats1': 0,
                        'inherent': 0,
                        'stats3': 0,
                        'stats4': 0
                    }
                ),
                'chain': 0
            }
        )
    )


def resonatorScraper(
    controller: WindowsInputController,
    screenInfo: ScreenInfo,
    expectedCount: int = 20,
):
    characters = _emptyCharacters()
    _cache: dict = {}
    menu = MainMenuController()

    # Terminal first — name-ROI fallback on Resonator detection can false-positive.
    if menu.isMenu():
        # From Terminal, click the Resonators tile — ESC+C is unreliable and was
        # leaving us stuck on Terminal (live debug 2026-08-01).
        tile = getattr(screenInfo.characters, "terminalResonators", None)
        if tile is None:
            logger.error("Characters: no terminalResonators coordinate for this resolution")
            return dict(characters)
        logger.info("Characters: on Terminal — clicking Resonators at (%s,%s)", tile.x, tile.y)
        controller.leftClick(tile.x, tile.y, 0.3)
        time.sleep(1.2)
    elif isOnResonatorScreen(screenInfo):
        # Already in Resonators (often Echo/Weapon). Do NOT press C — that closes it.
        logger.info("Characters: already on Resonator screen — switching to Overview")
        if not ensureResonatorOverview(controller, screenInfo):
            logger.error("Characters: could not switch to Overview from current Resonator tab")
            return dict(characters)
    else:
        key = cfg.get(cfg.resonatorKeybind)
        logger.info("Characters: pressing resonator key %r", key)
        controller.pressKey(key, 2, False)
        time.sleep(0.8)

    if menu.isMenu():
        logger.error("Characters: still on Terminal after open attempt")
        return dict(characters)

    if not isOnResonatorOverview(screenInfo):
        # Hotkey may open on a non-Overview tab; click Overview once.
        if isOnResonatorScreen(screenInfo):
            ensureResonatorOverview(controller, screenInfo)
        else:
            time.sleep(0.7)
        if not isOnResonatorOverview(screenInfo) and not isOnResonatorScreen(screenInfo):
            logger.error("Characters: Overview screen not detected after open attempt")
            return dict(characters)

    # Land on Overview, then map left-rail tabs via header OCR (safe detail nav).
    controller.leftClick(screenInfo.characters.leftSide.x, screenInfo.characters.leftSide.y, 0.35)
    time.sleep(0.35)
    tabMap: dict[str, tuple[int, int]] = {}
    if any((SCRAPE_WEAPON, SCRAPE_SKILLS, SCRAPE_CHAIN, SCRAPE_ECHOES)):
        logger.info("Characters: discovering resonator tabs")
        tabMap = discoverResonatorTabs(controller, screenInfo)
        logger.info("Characters: tab map %s", tabMap)

    xRightSide = int(screenInfo.characters.rightSide.x)
    yRightSide = int(screenInfo.characters.rightSide.y)
    yStep = int(screenInfo.characters.offsets.rightSide.y)
    # 1440p shows 6 portraits; a 7th click hits the grid button under the list.
    slotCount = int(getattr(screenInfo.characters, "rosterSlots", 6) or 6)
    slotYs = list(getattr(screenInfo.characters, "rosterSlotYs", None) or [])
    if len(slotYs) < slotCount:
        slotYs = [yRightSide + yStep * i for i in range(slotCount)]
    else:
        slotYs = [int(y) for y in slotYs[:slotCount]]
    # Drag ON the portrait column (not left into the model, not off the right edge).
    dragX = xRightSide
    yRosterMin = min(slotYs)
    yRosterMax = max(slotYs)
    dragMidY = (yRosterMin + yRosterMax) // 2
    # Full-page drag from live recording (tools/record_roster_clicks.py).
    # Falls back to one-portrait step if unset.
    recordedJump = getattr(screenInfo.characters, "pageJumpDrag", None)
    pageJumpDrag = int(recordedJump) if recordedJump else -int(yStep)
    jumpStart = getattr(screenInfo.characters, "pageJumpStart", None)
    jumpEnd = getattr(screenInfo.characters, "pageJumpEnd", None)
    jumpDuration = float(getattr(screenInfo.characters, "pageJumpDurationS", 0) or 0)
    jumpPath = None
    try:
        from pathlib import Path
        import json as _json
        jumpPath = None
        for pathFile in (
            Path(__file__).resolve().parents[1] / "data" / "roster_page_jump.json",
            Path("data") / "roster_page_jump.json",
            Path(__file__).resolve().parents[1] / "updater" / "roster_page_jump.json",
        ):
            if pathFile.is_file():
                jumpPath = _json.loads(pathFile.read_text(encoding="utf-8"))
                break
        if jumpPath:
            if jumpPath.get("deltaY") is not None:
                pageJumpDrag = int(jumpPath["deltaY"])
            if jumpPath.get("durationS"):
                jumpDuration = float(jumpPath["durationS"])
    except Exception:
        logger.debug("No roster_page_jump.json path replay", exc_info=True)
    clickWait = 0.2
    clickSettle = 0.14
    rosterSettle = 0.7  # list has inertia — never click while still sliding

    def _slotY(resonatorIndex: int) -> int:
        if 0 <= resonatorIndex < len(slotYs):
            return int(slotYs[resonatorIndex])
        return int(yRightSide + yStep * resonatorIndex)

    def _waitRosterSettle(extra: float = 0.0) -> None:
        time.sleep(rosterSettle + extra)

    def _rosterDrag(deltaY: int, wait: float = 0.18, *, maxDist: int | None = None) -> None:
        """Drag inside the right-hand portrait column."""
        dist = int(deltaY)
        cap = int(yStep if maxDist is None else maxDist)
        if cap > 0 and abs(dist) > cap:
            dist = cap if dist > 0 else -cap
        startY = dragMidY - dist // 2
        endY = startY + dist
        startY = max(yRosterMin, min(yRosterMax, startY))
        endY = max(yRosterMin, min(yRosterMax, endY))
        if startY == endY:
            endY = max(yRosterMin, min(yRosterMax, startY + (-yStep if dist < 0 else yStep)))
        controller.moveMouse(dragX, startY, 0.06)
        time.sleep(0.06)
        controller.dragMouse(dragX, startY, dragX, endY, steps=18, waitTime=wait)

    def _pageJump() -> None:
        """Advance roster by one visible page — replay timed user drag when available."""
        samples = (jumpPath or {}).get("samples") if isinstance(jumpPath, dict) else None
        if samples and len(samples) >= 2:
            logger.info(
                "Page jump path replay pts=%s duration=%.3fs Δy=%s",
                len(samples), jumpDuration or samples[-1].get("t"), pageJumpDrag,
            )
            controller.dragMousePath(samples, waitTime=0.4)
            return
        if jumpStart is not None and jumpEnd is not None and getattr(jumpStart, 'y', None) is not None:
            sx = int(jumpStart.x or dragX)
            sy = int(jumpStart.y)
            ex = int(jumpEnd.x or dragX)
            ey = int(jumpEnd.y)
            dur = jumpDuration if jumpDuration > 0.15 else 0.9
            steps = max(20, int(dur / 0.02))
            stepDelay = dur / steps
            controller.moveMouse(sx, sy, 0.1)
            time.sleep(0.1)
            controller.dragMouse(sx, sy, ex, ey, steps=steps, waitTime=0.4, stepDelay=stepDelay)
            return
        _rosterDrag(pageJumpDrag, wait=0.35, maxDist=abs(pageJumpDrag) + 80)
    def _clickOCR(clickY: int, *, keep: bool = True) -> str | None:
        controller.leftClick(xRightSide, clickY, clickWait)
        time.sleep(clickSettle)
        image = screenshot(
            width=screenInfo.width,
            height=screenInfo.height,
            monitor=screenInfo.monitor,
        )
        before = set(characters.keys())
        resonatorID, _stop = scrapeResonator(image, screenInfo, characters, _cache)
        if resonatorID and not keep and resonatorID not in before:
            characters.pop(resonatorID, None)
        return resonatorID

    def _readSlot(resonatorIndex: int, *, keep: bool = True, nudge: bool = False) -> str | None:
        clickY = _slotY(resonatorIndex)
        resonatorID = _clickOCR(clickY, keep=keep)
        if not resonatorID and nudge:
            for dy in (-yStep // 2, 28):
                resonatorID = _clickOCR(clickY + dy, keep=keep)
                if resonatorID:
                    logger.info("Slot %s recovered with nudge=%s → %s", resonatorIndex, dy, resonatorID)
                    break
        return resonatorID

    def _scrapeSlot(resonatorIndex: int, *, nudge: bool = False) -> tuple[str | None, bool, bool]:
        before = set(characters.keys())
        resonatorID = _readSlot(resonatorIndex, keep=True, nudge=nudge)
        if not resonatorID:
            return None, False, False
        if resonatorID in before:
            return resonatorID, True, False
        # New resonator — scrape weapon / forte / chain / echoes while selected.
        scrapeCharacterDetails(
            controller, screenInfo, characters, resonatorID, _cache, tabMap,
        )
        ensureResonatorOverview(controller, screenInfo)
        return resonatorID, False, True

    def _flingToTop() -> None:
        """Repeated 1-slot drags + wheel on the portrait column, then settle."""
        controller.moveMouse(dragX, dragMidY, 0.05)
        time.sleep(0.05)
        for _ in range(10):
            _rosterDrag(int(yStep), wait=0.06)
        controller.moveMouse(dragX, dragMidY, 0.03)
        for _ in range(10):
            controller.mouseScroll(1.0, 0.02)
        _waitRosterSettle(0.15)

    def _rosterToTop() -> str | None:
        """Scroll to first resonator; verify down-probe changes the top id."""
        logger.info("Characters: resetting roster to top")
        for attempt in range(2):
            _flingToTop()
            candidate = _readSlot(0, keep=False)
            if not candidate:
                continue
            _rosterDrag(pageJumpDrag, wait=0.1)
            _waitRosterSettle()
            moved = _readSlot(0, keep=False)
            if moved and moved != candidate:
                _flingToTop()
                kept = _readSlot(0, keep=True)
                logger.info("Characters: roster top on %s (verified)", kept or candidate)
                return kept or candidate
            logger.warning("Roster top probe stuck on %s (attempt %s)", candidate, attempt + 1)
        kept = _readSlot(0, keep=True)
        logger.info("Characters: roster top on %s (unverified)", kept)
        return kept

    seeded = _rosterToTop()
    # Roster-to-top already inserted the first char without detail scrape.
    if seeded and seeded in characters:
        scrapeCharacterDetails(controller, screenInfo, characters, seeded, _cache, tabMap)
        ensureResonatorOverview(controller, screenInfo)

    def _scanVisiblePage(pageIdx: int, startSlot: int = 0) -> int:
        if not isOnResonatorScreen(screenInfo):
            logger.warning("Left Resonator screen while scanning — aborting character loop")
            return 0
        found = 0
        prevRid = None
        prevDup = False
        prevOne = characterAliases.get('one')
        prevOe = characterAliases.get('oe')
        for resonatorIndex in range(startSlot, slotCount):
            endSlot = resonatorIndex >= slotCount - 2
            wantAalto = (
                endSlot
                and charactersID.get('aalto') not in characters
                and charactersID.get('taoqi') in characters
            )
            if wantAalto:
                characterAliases['one'] = 'aalto'
                characterAliases['oe'] = 'aalto'
            try:
                rid, dup, isNew = _scrapeSlot(resonatorIndex, nudge=wantAalto)
            finally:
                if wantAalto:
                    if prevOne is None:
                        characterAliases.pop('one', None)
                    else:
                        characterAliases['one'] = prevOne
                    if prevOe is None:
                        characterAliases.pop('oe', None)
                    else:
                        characterAliases['oe'] = prevOe
            if isNew:
                # Half-scrolled portrait between a dup and a new (e.g. Verina).
                if prevDup and prevRid and resonatorIndex > 0:
                    beforeGap = set(characters.keys())
                    gapY = (_slotY(resonatorIndex) + _slotY(resonatorIndex - 1)) // 2
                    gapId = _clickOCR(gapY, keep=True)
                    if gapId and gapId not in beforeGap:
                        scrapeCharacterDetails(
                            controller, screenInfo, characters, gapId, _cache, tabMap,
                        )
                        ensureResonatorOverview(controller, screenInfo)
                        found += 1
                        logger.info(
                            "Page %s gap before slot %s → %s (have %s)",
                            pageIdx, resonatorIndex, gapId, len(characters),
                        )
                found += 1
                prevDup = False
                logger.info(
                    "Page %s slot %s → %s (have %s)",
                    pageIdx, resonatorIndex, rid, len(characters),
                )
                prevRid = rid
            elif dup:
                prevDup = True
                prevRid = rid
                logger.debug("Page %s slot %s duplicate %s", pageIdx, resonatorIndex, rid)
            else:
                prevDup = False
        return found

    def _huntMissingAalto() -> bool:
        aaltoId = charactersID.get('aalto')
        taoqiId = charactersID.get('taoqi')
        chixiaId = charactersID.get('chixia')
        if not aaltoId or aaltoId in characters:
            return False
        if taoqiId not in characters or chixiaId not in characters:
            return False
        logger.info("Hunting missing Aalto between Taoqi and Chixia")
        prevOne = characterAliases.get('one')
        prevOe = characterAliases.get('oe')
        characterAliases['one'] = 'aalto'
        characterAliases['oe'] = 'aalto'
        for junk in ('aalfo', 'aaito', 'aalio', 'aa1to', 'alto', 'aalito', 'aal', 'aa'):
            characterAliases.setdefault(junk, 'aalto')
        try:
            huntYs: list[int] = []
            try:
                from pathlib import Path
                import json as _json
                aaltoFile = Path(__file__).resolve().parents[1] / 'data' / 'aalto_click.json'
                if aaltoFile.is_file():
                    raw = _json.loads(aaltoFile.read_text(encoding='utf-8'))
                    if raw.get('y') is not None:
                        huntYs.append(int(raw['y']))
                    for c in raw.get('clicks') or []:
                        if isinstance(c, (list, tuple)) and len(c) >= 2:
                            huntYs.append(int(c[1]))
                    logger.info("Aalto hunt using recorded click(s) %s", huntYs[:5])
            except Exception:
                logger.debug("No aalto_click.json", exc_info=True)

            yLo = min(_slotY(3), _slotY(4), _slotY(5))
            yHi = max(_slotY(3), _slotY(4), _slotY(5))
            huntYs.extend([
                _slotY(4),
                (_slotY(3) + _slotY(4)) // 2,
                (_slotY(4) + _slotY(5)) // 2,
            ])
            huntYs.extend(range(yLo, yHi + 1, 18))
            seen: set[int] = set()
            orderedYs: list[int] = []
            for y in huntYs:
                if y not in seen:
                    seen.add(y)
                    orderedYs.append(y)

            for y in orderedYs:
                before = set(characters.keys())
                # Two attempts with longer settle — Aalto name OCR often lags.
                for attempt in range(2):
                    controller.leftClick(xRightSide, y, clickWait)
                    time.sleep(0.45 + 0.15 * attempt)
                    image = screenshot(
                        width=screenInfo.width,
                        height=screenInfo.height,
                        monitor=screenInfo.monitor,
                    )
                    hit, _ = scrapeResonator(image, screenInfo, characters, _cache)
                    if aaltoId in characters or hit == aaltoId:
                        if aaltoId not in before:
                            scrapeCharacterDetails(
                                controller, screenInfo, characters, aaltoId, _cache, tabMap,
                            )
                            ensureResonatorOverview(controller, screenInfo)
                        logger.info("Aalto hunt hit y=%s attempt=%s", y, attempt)
                        return True
        finally:
            if prevOne is None:
                characterAliases.pop('one', None)
            else:
                characterAliases['one'] = prevOne
            if prevOe is None:
                characterAliases.pop('oe', None)
            else:
                characterAliases['oe'] = prevOe
        return aaltoId in characters

    maxPages = 18
    pageIdx = 0
    stagnant = 0
    while pageIdx < maxPages:
        msg = f"[characters] page {pageIdx + 1}/{maxPages} — have {len(characters)}/{expectedCount}"
        print(msg, flush=True)
        logger.info(msg)
        # page0: slot0 seeded. Later pages: scan all 6 (slot0 can be the only new one).
        startSlot = 1 if (pageIdx == 0 and seeded) else 0
        found = _scanVisiblePage(pageIdx, startSlot=startSlot)
        if not isOnResonatorScreen(screenInfo):
            return dict(characters)

        if len(characters) >= expectedCount:
            logger.info("Reached expected count %s — done", expectedCount)
            break

        if found == 0 and pageIdx > 0:
            stagnant += 1
            if stagnant >= 2:
                logger.info("No new resonators for 2 pages — stopping (count=%s)", len(characters))
                break
        else:
            stagnant = 0

        if pageIdx >= maxPages - 1:
            break
        # Only Aalto missing → hunt in place (don't keep paging empty bottom).
        missing = expectedCount - len(characters)
        if missing == 1 and charactersID.get('aalto') not in characters:
            break

        logger.info("Page %s jump drag=%s (slow)", pageIdx, pageJumpDrag)
        _pageJump()
        _waitRosterSettle(0.55)
        pageIdx += 1

    _huntMissingAalto()

    print(f"[characters] DONE {len(characters)}/{expectedCount}", flush=True)
    logger.info("Characters finished count=%s", len(characters))
    return dict(characters)
