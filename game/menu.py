import time
import logging
import re
from difflib import SequenceMatcher

from game.foreground import WindowManager
from scraping.utils.common import definedText
from scraping.utils import (
    screenshot, imageToString, convertToBlackWhite
)

logger = logging.getLogger('MainMenuController')

TERMINAL_TEXT_KEY = 'PrefabTextItem_1547656443_Text'


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
    # Compare against sliding windows around target length
    window = max(len(target), 4)
    best = 0.0
    if len(normalized) <= window + 2:
        best = SequenceMatcher(None, normalized, target).ratio()
    else:
        for i in range(0, len(normalized) - len(target) + 1):
            chunk = normalized[i:i + len(target)]
            best = max(best, SequenceMatcher(None, chunk, target).ratio())
    return best >= cutoff


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

    def isInMainMenu(self):
        """
        Checks if the application is in the main menu and handles errors if not.

        Returns:
            tuple: A tuple of three elements:
                - Status code (str): Empty string on success, 'error' on failure.
                - Status message (str): Descriptive message based on the result.
                - Additional information (str): Empty string on success, error message on failure.
        """
        try:
            result = WindowManager().setForeground()
            if result[0] == 'error':
                return result
            time.sleep(.2)

            if not self.isMenu():
                return 'error', 'Error', 'Not in the main menu. Press ESC in-game and rerun the scanner.'

            return '', '', ''

        except Exception as e:
            logger.error(f"Exception occurred: {e}", exc_info=True)
            return 'error', 'Exception', str(e)
