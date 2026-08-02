import re
import cv2
import time
import numpy as np
from pathlib import Path
from difflib import get_close_matches as getMatches

from scraping.utils import itemsID
from scraping.utils import (
    screenshot, imageToString, convertToBlackWhite,
    WindowsInputController, GridPageScroller
)
from game.screenInfo import ScreenInfo
from game.menu import MainMenuController, looksLikeTerminalFeatureNoise
from properties.config import cfg, basePATH

# Constants
ROWS, COLS = 4, 6

def _normKey(text: str) -> str:
    """Alnum-only key so OCR can match hyphen / apostrophe variants."""
    return ''.join(ch for ch in (text or '').lower() if ch.isalnum())


def _matchItemName(raw: str) -> str | None:
    """Fuzzy-match OCR text to an items.json key; None if nothing close enough."""
    text = _normKey(raw)
    if not text:
        return None
    # OCR often reads Roman III as "lil" / II as "il".
    variants = [text]
    if text.endswith('lil'):
        variants.append(text[:-3] + 'iii')
    if text.endswith('il') and not text.endswith('lil'):
        variants.append(text[:-2] + 'ii')
    keyed = {_normKey(k): k for k in itemsID}
    for candidate in variants:
        if candidate in keyed:
            return keyed[candidate]
        for cutoff in (0.9, 0.85, 0.8):
            hit = getMatches(candidate, keyed.keys(), 1, cutoff)
            if hit:
                return keyed[hit[0]]
    return None


def processItem(path: Path, image: np.ndarray, screenInfo: ScreenInfo, _cache: dict) -> tuple[dict[str, int], list[dict]]:
    inventory = {}
    failed = []

    infoImage = image[screenInfo.items.info.y:screenInfo.items.info.y + screenInfo.items.info.h, screenInfo.items.info.x:screenInfo.items.info.x + screenInfo.items.info.w]
    infoImage = convertToBlackWhite(infoImage)
    infoHash = hash(infoImage.tobytes())

    if infoHash in _cache:
        info = _cache[infoHash]
    else:
        info = imageToString(infoImage, bannedChars=' ').lower().split('\n')
        _cache[infoHash] = info
    rawName = info[0] if info else ''
    matched = _matchItemName(rawName)
    name = matched if matched else rawName
    
    try: value = re.sub(r'[^0-9]', '', info[2])
    except: value = 1

    try: value = int(value)
    except ValueError: value = 1

    itemID = itemsID.get(name, {'id': None})['id']
    if itemID is not None:
        inventory[itemID] = value
    else:
        path.mkdir(parents=True, exist_ok=True)
        descImage = image[screenInfo.items.description.y:screenInfo.items.description.y + screenInfo.items.description.h, screenInfo.items.description.x:screenInfo.items.description.x + screenInfo.items.description.w]

        imagePath = path / f'_{rawName}-{time.time()}.png'
        cv2.imwrite(imagePath, descImage)

        failed.append({
            'image': imagePath,
            'owned': value
        })

    return inventory, failed, name

def itemsScraper(START_DATE: str, controller: WindowsInputController, x: int, y: int, screenInfo: ScreenInfo):
    path: Path = basePATH / 'logs' / 'fail' / START_DATE
    
    inventory = dict()
    failed = list()
    encounters = dict()
    _cache = dict()
    menu = MainMenuController()

    # Hotkeys only work from gameplay — never click the item grid on Terminal.
    if menu.isMenu() and not menu.ensureGameplay(controller):
        return inventory, failed

    controller.pressKey(cfg.get(cfg.inventoryKeybind), 2, False)
    time.sleep(0.5)
    if menu.isMenu():
        # Inventory key ignored (still on pause menu) — abort instead of clicking Podcast tiles.
        return inventory, failed

    controller.leftClick(x, y)

    isDouble = False
    last = ""
    scroller = GridPageScroller(controller, screenInfo, screenInfo.items, ROWS, COLS, 'items')

    while not isDouble:
        for row in range(ROWS):
            for col in range(COLS):
                center_x = screenInfo.items.start.x + (col * (screenInfo.items.start.w + screenInfo.offsets.page.x)) + screenInfo.items.start.w // 2
                center_y = screenInfo.items.start.y + (row * (screenInfo.items.start.h + screenInfo.offsets.page.y)) + screenInfo.items.start.h // 2
                
                controller.leftClick(center_x, center_y)
                image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
                
                item_inventory, item_failed, name = processItem(path, image, screenInfo, _cache)
                if looksLikeTerminalFeatureNoise(name) or menu.isMenu():
                    # Wrong screen (e.g. Pioneer Podcast tiles) — stop immediately.
                    del _cache
                    return {}, []

                inventory.update(item_inventory)
                failed.extend(item_failed)

                value = inventory.get(itemsID.get(name, {'id': None})['id'], 1)
                maxEncounters = np.ceil(value / 999)
                encounters[name] = encounters.get(name, 0) + 1

                if encounters[name] > maxEncounters:
                    last = name
                    isDouble = True
                    break
            if isDouble:
                break
        
        if not isDouble and not scroller.scrollPage():
            break

    # Process last page
    isDouble = False
    for row in range(ROWS - 1, -1, -1):
        for col in range(COLS - 1, -1, -1):
            center_x = screenInfo.items.start.x + (col * (screenInfo.items.start.w + screenInfo.offsets.page.x)) + screenInfo.items.start.w // 2
            center_y = screenInfo.items.start.y + (row * (screenInfo.items.start.h + screenInfo.offsets.page.y)) + screenInfo.items.start.h // 2
            
            controller.leftClick(center_x, center_y)
            image = screenshot(width=screenInfo.width, height=screenInfo.height, monitor=screenInfo.monitor)
            
            item_inventory, item_failed, name = processItem(path, image, screenInfo, _cache)
            
            if name == last:
                continue

            inventory.update(item_inventory)
            failed.extend(item_failed)

            value = inventory.get(itemsID.get(name, {'id': None})['id'], 1)
            maxEncounters = np.ceil(value / 999)
            encounters[name] = encounters.get(name, 0) + 1

            if encounters[name] > maxEncounters:
                isDouble = True
                break
        if isDouble:
            break
    
    del _cache
    return inventory, failed