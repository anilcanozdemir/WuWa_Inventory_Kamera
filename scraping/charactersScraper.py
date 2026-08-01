import re
import time
import string
import logging
from collections import defaultdict

from difflib import get_close_matches as getMatches

from scraping.utils import charactersID, weaponsID, definedText
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

# Weapon / Forte / Chain clicks are mis-aligned on current 1440p UI and were
# clicking into the world (normal-attack spam). Overview-only until recalibrated.
SCRAPE_WEAPON = False
SCRAPE_ECHOES = False
SCRAPE_SKILLS = False
SCRAPE_CHAIN = False


def parseLevelPair(text: str) -> tuple[int, int]:
    """Parse 'Lv. 80 / 80' (or OCR junk) into (level, ascensionCap)."""
    nums = [int(n) for n in re.findall(r'\d+', text or '')]
    if not nums:
        return 1, 0
    level = nums[0]
    cap = nums[1] if len(nums) > 1 else nums[0]
    try:
        ascension = ASCENSION_LEVELS.index(cap)
    except ValueError:
        ascension = 0
    return level, ascension


def isOnResonatorOverview(screenInfo: ScreenInfo) -> bool:
    """True when top-left header looks like Overview (not Terminal / gameplay)."""
    x = max(0, int(screenInfo.terminal.x) - 20)
    y = max(0, int(screenInfo.terminal.y) - 10)
    w = int(screenInfo.terminal.w) + 80
    h = int(screenInfo.terminal.h) + 40
    image = screenshot(x, y, w, h, screenInfo.monitor)
    text = normalizeMenuText(imageToString(image, ''))
    text_bw = normalizeMenuText(imageToString(convertToBlackWhite(image), ''))
    combined = text + text_bw
    ok = 'overview' in combined or 'verview' in combined
    logger.debug("Resonator overview OCR=%r/%r ok=%s", text, text_bw, ok)
    return ok


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
        resonatorName = imageToString(resonatorNameImage, '', bannedChars=' ').lower()
        if len(re.sub(r'[^a-z0-9]', '', resonatorName)) < 2:
            resonatorName = imageToString(
                convertToBlackWhite(resonatorNameImage), '', bannedChars=' '
            ).lower()
        resonatorName = re.sub(r'[^a-z0-9]', '', resonatorName)
        logger.debug("Resonator name OCR=%r", resonatorName)

        if len(resonatorName) < 2:
            _cache[resonatorNameHash] = None
            return None, False

        result = getMatches(resonatorName, list(charactersID), 1, 0.75)
        if result:
            resonatorName = result[0]

        rover = cfg.get(cfg.roverName).replace(' ', '').lower()
        resonatorID = (
            '1502'
            if resonatorName == rover
            else charactersID.get(resonatorName, resonatorName)
        )
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


def scrapeWeapon(image, screenInfo: ScreenInfo, characters: dict, resonatorID: str, _cache: dict):
    weaponNameImage = image[screenInfo.characters.weaponName.y:screenInfo.characters.weaponName.y + screenInfo.characters.weaponName.h, screenInfo.characters.weaponName.x:screenInfo.characters.weaponName.x + screenInfo.characters.weaponName.w]
    weaponNameImage = convertToBlackWhite(weaponNameImage)
    weaponNameHash = hash(weaponNameImage.tobytes())

    if weaponNameHash in _cache:
        weaponID = _cache[weaponNameHash]
    else:
        weaponName = imageToString(weaponNameImage, bannedChars=' ').lower()
    
        result = getMatches(weaponName, weaponsID, 1, 0.9)
        if result:
            weaponName = result[0]
        
        weaponID = weaponsID.get(weaponName, {'id': weaponName})['id']
        _cache[weaponNameHash] = weaponID
    
    levelImage = image[screenInfo.characters.weaponLevel.y:screenInfo.characters.weaponLevel.y + screenInfo.characters.weaponLevel.h, screenInfo.characters.weaponLevel.x:screenInfo.characters.weaponLevel.x + screenInfo.characters.weaponLevel.w]
    levelImage = convertToBlackWhite(levelImage)
    levelHash = hash(levelImage.tobytes())
    
    if levelHash in _cache:
        levelText = _cache[levelHash]
    else:
        levelText = imageToString(levelImage, '')
        _cache[levelHash] = levelText

    rankImage = image[screenInfo.characters.weaponRank.y:screenInfo.characters.weaponRank.y + screenInfo.characters.weaponRank.h, screenInfo.characters.weaponRank.x:screenInfo.characters.weaponRank.x + screenInfo.characters.weaponRank.w]
    rankImage = convertToBlackWhite(rankImage)
    rankHash = hash(rankImage.tobytes())

    if rankHash in _cache:
        rank = _cache[rankHash]
    else:
        rank = imageToString(rankImage, '', allowedChars=string.digits)
        _cache[rankHash] = rank

    try:
        level, ascension = parseLevelPair(levelText)
        characters[resonatorID]['weapon']['id'] = weaponID
        characters[resonatorID]['weapon']['level'] = level
        characters[resonatorID]['weapon']['ascension'] = ascension
        characters[resonatorID]['weapon']['rank'] = int(rank or 1)
    except Exception:
        logger.debug('Failed scraping the weapon')


def scrapeSkills(controller: WindowsInputController, screenInfo: ScreenInfo, characters: dict, resonatorID: str, _cache: dict):
    controller.leftClick(screenInfo.characters.skillClick.x, screenInfo.characters.skillClick.y, .5)

    for index, skills in enumerate(screenInfo.characters.skillPositions):
        controller.leftClick(skills.x, skills.y)

        image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor, bw=True)

        levelImage = image[screenInfo.characters.skillLevel.y:screenInfo.characters.skillLevel.y + screenInfo.characters.skillLevel.h, screenInfo.characters.skillLevel.x:screenInfo.characters.skillLevel.x + screenInfo.characters.skillLevel.w]
        levelHash = hash(levelImage.tobytes())
        
        if levelHash in _cache:
            level = _cache[levelHash]
        else:
            level = imageToString(levelImage, '', allowedChars=string.digits)
            _cache[levelHash] = level

        try:
            level = int(level)
        except Exception:
            level = 1
            _cache[levelHash] = level
            logger.debug('Failed scraping the skill level')

        characters[resonatorID]['skills'][SKILL_LEGENDS[index]] = level

        for y in range(1, 3):
            controller.leftClick(skills.x, skills.y - (screenInfo.characters.offsets.skillPosition.y * y), .6)

            buttonImage = screenshot(screenInfo.characters.skillButton.x, screenInfo.characters.skillButton.y, screenInfo.characters.skillButton.w, screenInfo.characters.skillButton.h, monitor=screenInfo.monitor, bw=True)
            buttonHash = hash(buttonImage.tobytes())

            if buttonHash in _cache:
                button = _cache[buttonHash]
            else:
                button = imageToString(buttonImage).lower()
                _cache[buttonHash] = button

            if button.lower() == definedText['PrefabTextItem_3963945691_Text']:
                key = 'inherent' if index == 2 else f'stats{index}'
                characters[resonatorID]['skills'][key] += 1
            else:
                break

    controller.pressKey('esc')


def scrapeChain(controller: WindowsInputController, screenInfo: ScreenInfo, characters: dict, resonatorID: str, _cache: dict):
    controller.leftClick(screenInfo.characters.chainClick.x, screenInfo.characters.chainClick.y, .7)

    for position in screenInfo.characters.chainPositions:
        controller.leftClick(position.x, position.y, .2)

        statusImage = screenshot(screenInfo.characters.chainButton.x, screenInfo.characters.chainButton.y, screenInfo.characters.chainButton.w, screenInfo.characters.chainButton.h, monitor=screenInfo.monitor)
        statusHash = hash(statusImage.tobytes())
        
        if statusHash in _cache:
            status = _cache[statusHash]
        else:
            status = imageToString(statusImage, '', bannedChars=f'{string.punctuation} ').lower()
            _cache[statusHash] = status

        if status.lower() != definedText['PrefabTextItem_3963945691_Text']:
            break

        characters[resonatorID]['chain'] += 1
    controller.pressKey('esc')


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


def resonatorScraper(controller: WindowsInputController, screenInfo: ScreenInfo):
    characters = _emptyCharacters()
    _cache: dict = {}
    menu = MainMenuController()

    if menu.isMenu() and not menu.ensureGameplay(controller):
        logger.error("Characters: still on Terminal, aborting")
        return dict(characters)

    key = cfg.get(cfg.resonatorKeybind)
    logger.info("Characters: pressing resonator key %r", key)
    controller.pressKey(key, 2, False)
    time.sleep(0.8)

    if menu.isMenu():
        logger.error("Characters: Terminal still open after %r — hotkey ignored", key)
        return dict(characters)

    if not isOnResonatorOverview(screenInfo):
        # One retry: hotkey sometimes opens the menu mid-animation.
        time.sleep(0.6)
        if not isOnResonatorOverview(screenInfo):
            logger.error("Characters: Overview screen not detected after %r", key)
            return dict(characters)

    # Stay on Overview — never click Forte/Chain (mis-clicks → world attacks).
    controller.leftClick(screenInfo.characters.leftSide.x, screenInfo.characters.leftSide.y, 0.5)

    xRightSide = screenInfo.characters.rightSide.x
    yRightSide = screenInfo.characters.rightSide.y
    yStep = screenInfo.characters.offsets.rightSide.y

    stagnantRounds = 0
    for page in range(8):
        foundOnPage = 0
        for resonatorIndex in range(7):
            controller.leftClick(
                xRightSide,
                yRightSide + (yStep * resonatorIndex),
                0.65,
            )
            time.sleep(0.25)

            if not isOnResonatorOverview(screenInfo):
                logger.warning("Left Overview while scanning — aborting character loop")
                return dict(characters)

            image = screenshot(
                width=screenInfo.width,
                height=screenInfo.height,
                monitor=screenInfo.monitor,
            )
            resonatorID, stop = scrapeResonator(image, screenInfo, characters, _cache)
            if stop:
                logger.info("Duplicate resonator %s — roster complete", resonatorID)
                return dict(characters)
            if resonatorID:
                foundOnPage += 1
                if SCRAPE_WEAPON:
                    controller.leftClick(
                        screenInfo.characters.leftSide.x,
                        screenInfo.characters.leftSide.y + screenInfo.characters.offsets.leftSide.y,
                        0.7,
                    )
                    image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
                    scrapeWeapon(image, screenInfo, characters, resonatorID, _cache)
                    controller.leftClick(screenInfo.characters.leftSide.x, screenInfo.characters.leftSide.y, 0.5)
                if SCRAPE_SKILLS:
                    scrapeSkills(controller, screenInfo, characters, resonatorID, _cache)
                if SCRAPE_CHAIN:
                    scrapeChain(controller, screenInfo, characters, resonatorID, _cache)

        if foundOnPage == 0:
            stagnantRounds += 1
            if stagnantRounds >= 2:
                logger.info("No new resonators for 2 pages — stopping")
                break
        else:
            stagnantRounds = 0

        controller.moveMouse(xRightSide, yRightSide, 0.3)
        controller.mouseScroll(screenInfo.scroll.characters.y, 0.5)
        time.sleep(0.35)

    logger.info("Characters finished count=%s", len(characters))
    return dict(characters)
