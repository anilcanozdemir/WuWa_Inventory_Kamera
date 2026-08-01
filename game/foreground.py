import ctypes
import logging
import time
import win32gui
import win32con
import win32process
import win32api

import mss
import pywinctl as pwc
import pymonctl as pmc

from game.screenInfo import ScreenInfo
from properties.config import PROCESS_NAME, WINDOW_NAME

logger = logging.getLogger('WindowManager')

class WindowManager:
	def __init__(self, windowName: str = WINDOW_NAME, preocessName: str = PROCESS_NAME):
		self.user32 = ctypes.WinDLL('user32', use_last_error=True)
		self.windowName = windowName
		self.preocessName = preocessName
		self.window = self._findWindow()

	def _findWindow(self) -> pwc.Window|None:
		"""Finds the window by title and process name."""
		for win in pwc.getWindowsWithTitle(title=self.windowName, app=self.preocessName, condition=pwc.Re.CONTAINS):
			return win
		# Title-only fallback: some builds report a different process name to pywinctl.
		for win in pwc.getWindowsWithTitle(title=self.windowName, condition=pwc.Re.CONTAINS):
			logger.debug("Matched window by title only: %s", getattr(win, "title", "?"))
			return win
		logger.debug(f"Window with WindowName: {self.windowName} and ProcessName: {self.preocessName}, not found.")
		return None

	def _forceForeground(self, hwnd: int) -> None:
		"""
		Best-effort focus steal. Windows blocks SetForegroundWindow unless the
		caller is foreground / attached; AttachThreadInput is the usual workaround.
		"""
		foreground = win32gui.GetForegroundWindow()
		if foreground == hwnd:
			return

		try:
			self.user32.AllowSetForegroundWindow(-1)
		except Exception:
			pass

		currentTid = win32api.GetCurrentThreadId()
		fgTid, _ = win32process.GetWindowThreadProcessId(foreground) if foreground else (0, 0)
		targetTid, _ = win32process.GetWindowThreadProcessId(hwnd)

		attached = False
		try:
			if fgTid and fgTid != currentTid:
				attached = bool(win32process.AttachThreadInput(currentTid, fgTid, True))
			if targetTid and targetTid != currentTid and targetTid != fgTid:
				win32process.AttachThreadInput(currentTid, targetTid, True)

			win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
			win32gui.BringWindowToTop(hwnd)
			win32gui.SetForegroundWindow(hwnd)
		except Exception as e:
			logger.warning("Force foreground failed: %s", e)
		finally:
			try:
				if fgTid and fgTid != currentTid:
					win32process.AttachThreadInput(currentTid, fgTid, False)
				if targetTid and targetTid != currentTid and targetTid != fgTid:
					win32process.AttachThreadInput(currentTid, targetTid, False)
			except Exception:
				pass
			_ = attached

	def setForeground(self) -> tuple:
		"""Brings the window to the foreground and maximizes it."""
		if self.window:
			hwnd = self.window._hWnd
			try:
				self.window.activate()
			except Exception as e:
				logger.warning("window.activate() failed: %s", e)
			try:
				win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
			except Exception as e:
				# Elevated game process can deny PostMessage from a non-admin scanner.
				logger.warning("PostMessage(WM_ACTIVATE) failed: %s", e)

			self._forceForeground(hwnd)
			time.sleep(0.15)

			fg = win32gui.GetForegroundWindow()
			if fg != hwnd:
				fgTitle = ""
				try:
					fgTitle = win32gui.GetWindowText(fg)
				except Exception:
					pass
				logger.error(
					"Game window is not foreground after activate "
					"(fg_hwnd=%s title=%r game_hwnd=%s). "
					"mss will capture whatever is on screen — usually Cursor/browser.",
					fg, fgTitle, hwnd,
				)
				return (
					"error",
					"Error",
					"Game is covered by another window. Alt+Tab to Wuthering Waves "
					"(ESC pause menu visible), run the scanner as Admin, then retry.",
				)

			logger.debug(f"Window {self.windowName} set to foreground.")
			return ("success", "Success", "pass")
		else:
			logger.debug(f"Cannot set {self.windowName} in foreground: window not found.")
			return ("error", "Error", f"Cannot set {self.windowName} in foreground: window not found.")

	def getWindowPosition(self) -> pmc.Point|None:
		"""Return the window's position."""
		if self.window:
			return self.window.position
		else:
			logger.debug("Cannot retrieve window position: window not found.")
			return None
	
	def getWindowSize(self) -> tuple[int, int]|None:
		"""Return the window's size."""
		if self.window:
			return self.window.width, self.window.height
		else:
			logger.debug("Cannot retrieve window size: window not found.")
			return None

	def resolveMssMonitorIndex(self) -> int:
		"""
		Map the game window to an mss monitor index by geometry.

		DISPLAY1/DISPLAY2 numbers from Win32 do not reliably match mss.monitors
		order on multi-monitor setups; using them caused OCR to read the wrong
		screen (browser text instead of the game).
		"""
		if not self.window:
			return 1

		pos = self.getWindowPosition()
		size = self.getWindowSize()
		if not pos or not size:
			return 1

		centerX = pos.x + size[0] / 2
		centerY = pos.y + size[1] / 2

		with mss.mss() as sct:
			# monitors[0] is the virtual desktop spanning all displays
			for index, mon in enumerate(sct.monitors[1:], start=1):
				left, top = mon["left"], mon["top"]
				right = left + mon["width"]
				bottom = top + mon["height"]
				if left <= centerX < right and top <= centerY < bottom:
					logger.debug(
						"Resolved mss monitor %s for window center (%.0f, %.0f) "
						"rect=(%s,%s)-(%s,%s)",
						index, centerX, centerY, left, top, right, bottom,
					)
					return index

		logger.warning(
			"Window center (%.0f, %.0f) not inside any mss monitor; defaulting to 1",
			centerX, centerY,
		)
		return 1
	
	def getScreenInfo(self) -> ScreenInfo:
		width, height = self.getWindowSize() or (1920, 1080)

		DPI = self.getDPI()
		monitor = self.resolveMssMonitorIndex()
		
		width = int(width / DPI)
		height = int(height / DPI)

		logger.debug(
			"ScreenInfo logical=%sx%s dpi=%s mss_monitor=%s",
			width, height, DPI, monitor,
		)
		
		return ScreenInfo(width, height, monitor)

	def _getScreen(self) -> pmc.Monitor:
		"""Return the primary screen object."""
		return pmc.getAllMonitors()[0]

	def getScreenSize(self) -> tuple[int, int]:
		"""Retrieves the primary screen size."""
		screen = self._getScreen()
		return screen.size.width, screen.size.height

	def getDPI(self) -> float:
		return self.user32.GetDpiForWindow(self.window._hWnd) / 96.0

	def isForeground(self) -> bool:
		"""Check if the window is still in foreground."""
		if self.window:
			return self.window.isActive
		return False
