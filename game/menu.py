import time
import logging
import re
from difflib import SequenceMatcher

from game.foreground import WindowManager
from scraping.utils.common import definedText
from scraping.utils import (
    screenshot, imageToString, convertToBlackWhite
)
from scraping.utils.mouse_keyboard import WindowsInputController

logger = logging.getLogger('MainMenuController')

TERMINAL_TEXT_KEY = 'PrefabTextItem_1547656443_Text'

# OCR junk seen when scrapers click the Terminal feature grid instead of inventory.
TERMINAL_FEATURE_MARKERS = (
    'pioneer', 'convene', 'databank', 'wavesline', 'expedition', 'trophies',
    'podcast', 'motorbike',
)


def normalizeMenuText(value: str) -> str:
    """Match definedText.json normalization (lower, strip spaces/dashes)."""
    return re.sub(r'[\s\-]+', '', (value or '').lower()).strip()


def textLooksLikeTerminal(ocrText: str, expected: str, cutoff: float = 0.72) -> bool:
    """
    True when OCR of the Terminal ROI matches the expected Terminal label.

    Uses substring containment plus fuzzy ratio so minor OCR noise
    (O/0, missing letters, extra neighboring glyphs) still passes.
    """
    normalized = normalizeMenuText(ocrText)
    target = normalizeMenuText(expected)
    if not normalized or not target:
        return False
    if target in normalized or normalized in target:
        return True
    if len(normalized) <= len(target) + 2:
        return SequenceMatcher(None, normalized, target).ratio() >= cutoff
    best = 0.0
    for i in range(0, len(normalized) - len(target) + 1):
        chunk = normalized[i:i + len(target)]
        best = max(best, SequenceMatcher(None, chunk, target).ratio())
    return best >= cutoff


def looksLikeTerminalFeatureNoise(name: str) -> bool:
    """True when an 'item name' is clearly a Terminal menu tile OCR."""
    normalized = normalizeMenuText(name)
    return any(marker in normalized for marker in TERMINAL_FEATURE_MARKERS)


class MainMenuController:
    """Handles interactions with the screen and performs actions based on visual content."""

    def isMenu(self) -> bool:
        """
        Checks if the current screen shows the main menu.

        Returns:
            bool: True if the main menu is detected, False otherwise.
        """
        try:
            screenInfo = WindowManager().getScreenInfo()
            expected = definedText.get(TERMINAL_TEXT_KEY, 'terminal')

            # Slightly larger than the baked ROI: post-3.3 UI shifts still land here.
            x = max(0, int(screenInfo.terminal.x) - 20)
            y = max(0, int(screenInfo.terminal.y) - 10)
            w = int(screenInfo.terminal.w) + 60
            h = int(screenInfo.terminal.h) + 30

            image = screenshot(x, y, w, h, screenInfo.monitor)
            raw = imageToString(image, '')
            bw = imageToString(convertToBlackWhite(image), '')

            matched = textLooksLikeTerminal(raw, expected) or textLooksLikeTerminal(bw, expected)
            logger.debug(
                "Main menu OCR raw=%r bw=%r expected=%r matched=%s roi=(%s,%s,%s,%s) monitor=%s",
                raw, bw, expected, matched, x, y, w, h, screenInfo.monitor,
            )
            return matched
        except Exception as e:
            logger.error(f"Failed to capture or process screenshot: {e}", exc_info=True)
            return False

    def ensureGameplay(self, controller: WindowsInputController, maxEscapes: int = 2) -> bool:
        """
        Leave the Terminal pause menu so gameplay / hotkeys (B, C) work.

        Returns True when Terminal is no longer detected.
        """
        for attempt in range(1, maxEscapes + 1):
            if not self.isMenu():
                return True
            logger.info("Leaving Terminal pause menu (ESC attempt %s)", attempt)
            controller.pressKey('esc', 0.55)
            time.sleep(0.45)
        stillOpen = self.isMenu()
        if stillOpen:
            logger.error("Still on Terminal after ESC — refusing to click inventory grid.")
        return not stillOpen

    def isInMainMenu(self):
        """
        Switch to the game from the scanner UI and make sure Terminal is readable
        once (scrapers then leave Terminal themselves via ESC).

        Returns:
            tuple: (status, title, detail) — status '' on success, 'error' on failure.
        """
        try:
            game = WindowManager()
            result = game.setForeground()
            if result[0] == 'error':
                return result

            time.sleep(0.4)
            screenInfo = game.getScreenInfo()

            if self.isMenu():
                logger.debug("Terminal already visible after focus")
                return '', '', ''

            # One ESC only — do not spam; scrapers also press ESC.
            logger.info("Terminal not visible — pressing ESC once to open pause menu.")
            WindowsInputController(screenInfo.monitor).pressKey('esc', 0.6)
            time.sleep(0.5)

            if self.isMenu():
                return '', '', ''

            return (
                'error',
                'Error',
                'Switched to the game but could not read the Terminal menu. '
                'Use exclusive fullscreen / borderless at 1080p or 1440p, English UI, then retry.',
            )

        except Exception as e:
            logger.error(f"Exception occurred: {e}", exc_info=True)
            return 'error', 'Exception', str(e)
