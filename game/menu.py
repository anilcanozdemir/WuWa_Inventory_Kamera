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

    def _openPauseMenuIfNeeded(self, screenInfo) -> None:
        """If Terminal is not visible, press ESC so the pause menu opens."""
        if self.isMenu():
            return
        logger.info("Terminal not visible — pressing ESC to open pause menu.")
        controller = WindowsInputController(screenInfo.monitor)
        controller.pressKey('esc', 0.6)
        time.sleep(0.4)

    def isInMainMenu(self):
        """
        Switch to the game from the scanner UI, open the pause menu if needed,
        then verify Terminal is readable.

        Returns:
            tuple: (status, title, detail) — status '' on success, 'error' on failure.
        """
        try:
            game = WindowManager()
            result = game.setForeground()
            if result[0] == 'error':
                return result

            # Give the game a moment to present after focus steal.
            time.sleep(0.35)
            screenInfo = game.getScreenInfo()

            # Up to 3 tries: focus is already on game; ESC opens Terminal if closed.
            for attempt in range(1, 4):
                if self.isMenu():
                    logger.debug("Main menu ready on attempt %s", attempt)
                    return '', '', ''
                self._openPauseMenuIfNeeded(screenInfo)
                # Re-focus in case ESC somehow bounced focus.
                focus = game.setForeground()
                if focus[0] == 'error':
                    return focus

            return (
                'error',
                'Error',
                'Switched to the game but could not read the Terminal menu. '
                'Use exclusive fullscreen / borderless at 1080p or 1440p, English UI, then retry.',
            )

        except Exception as e:
            logger.error(f"Exception occurred: {e}", exc_info=True)
            return 'error', 'Exception', str(e)
