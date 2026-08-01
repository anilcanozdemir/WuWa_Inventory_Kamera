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

# Virtual-key for Alt — brief press unlocks SetForegroundWindow on modern Windows.
VK_MENU = 0x12
KEYEVENTF_KEYUP = 0x0002


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

	@staticmethod
	def minimizeByTitle(titleSubstring: str) -> None:
		"""Minimize every top-level window whose title contains titleSubstring."""
		matches: list[int] = []

		def _enum(hwnd, _):
			if not win32gui.IsWindowVisible(hwnd):
				return
			try:
				title = win32gui.GetWindowText(hwnd)
			except Exception:
				return
			if title and titleSubstring.lower() in title.lower():
				matches.append(hwnd)

		win32gui.EnumWindows(_enum, None)
		for hwnd in matches:
			try:
				win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
				logger.debug("Minimized window hwnd=%s title=%r", hwnd, win32gui.GetWindowText(hwnd))
			except Exception as e:
				logger.warning("Failed to minimize hwnd=%s: %s", hwnd, e)

	@staticmethod
	def restoreByTitle(titleSubstring: str) -> None:
		"""Restore minimized windows matching titleSubstring and try to focus the first."""
		matches: list[int] = []

		def _enum(hwnd, _):
			try:
				title = win32gui.GetWindowText(hwnd)
			except Exception:
				return
			if title and titleSubstring.lower() in title.lower():
				matches.append(hwnd)

		win32gui.EnumWindows(_enum, None)
		for hwnd in matches:
			try:
				win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
			except Exception:
				pass
		if matches:
			try:
				win32gui.SetForegroundWindow(matches[0])
			except Exception:
				pass

	def _altUnlock(self) -> None:
		"""Synthetic Alt tap — common unlock for SetForegroundWindow restrictions."""
		try:
			self.user32.keybd_event(VK_MENU, 0, 0, 0)
			time.sleep(0.02)
			self.user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
		except Exception as e:
			logger.debug("Alt unlock failed: %s", e)

	def _forceForeground(self, hwnd: int) -> None:
		"""
		Best-effort focus steal. Windows blocks SetForegroundWindow unless the
		caller is foreground / attached; AttachThreadInput + Alt unlock are the
		usual workarounds. Called right after a UI button click so we usually
		still hold foreground permission.
		"""
		foreground = win32gui.GetForegroundWindow()
		if foreground == hwnd:
			return

		try:
			self.user32.AllowSetForegroundWindow(-1)
		except Exception:
			pass

		self._altUnlock()

		currentTid = win32api.GetCurrentThreadId()
		fgTid, _ = win32process.GetWindowThreadProcessId(foreground) if foreground else (0, 0)
		targetTid, _ = win32process.GetWindowThreadProcessId(hwnd)

		try:
			if fgTid and fgTid != currentTid:
				win32process.AttachThreadInput(currentTid, fgTid, True)
			if targetTid and targetTid != currentTid and targetTid != fgTid:
				win32process.AttachThreadInput(currentTid, targetTid, True)

			win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
			win32gui.BringWindowToTop(hwnd)
			try:
				win32gui.SetWindowPos(
					hwnd,
					win32con.HWND_TOPMOST,
					0, 0, 0, 0,
					win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
				)
				win32gui.SetWindowPos(
					hwnd,
					win32con.HWND_NOTOPMOST,
					0, 0, 0, 0,
					win32con.SWP_NOMOVE | win32con.SWP_NOSIZE,
				)
			except Exception:
				pass
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

	def setForeground(
		self,
		retries: int = 8,
		settleSeconds: float = 0.25,
		minimizeScanner: bool = True,
	) -> tuple:
		"""
		Bring this window to the foreground.

		When focusing the game for a scan (`minimizeScanner=True`), the Kamera
		UI is minimized first so it cannot cover the capture region.
		"""
		if not self.window:
			logger.debug(f"Cannot set {self.windowName} in foreground: window not found.")
			return ("error", "Error", f"Cannot set {self.windowName} in foreground: window not found.")

		if minimizeScanner and self.windowName == WINDOW_NAME:
			self.minimizeByTitle('WuWa Inventory Kamera')
			time.sleep(0.1)

		hwnd = self.window._hWnd
		for attempt in range(1, retries + 1):
			try:
				self.window.activate()
			except Exception as e:
				logger.debug("window.activate() attempt %s failed: %s", attempt, e)
			try:
				win32gui.PostMessage(hwnd, win32con.WM_ACTIVATE, win32con.WA_ACTIVE, 0)
			except Exception as e:
				logger.debug("PostMessage(WM_ACTIVATE) attempt %s failed: %s", attempt, e)

			self._forceForeground(hwnd)
			time.sleep(settleSeconds)

			fg = win32gui.GetForegroundWindow()
			if fg == hwnd:
				logger.debug(
					"Window %s set to foreground on attempt %s.",
					self.windowName, attempt,
				)
				return ("success", "Success", "pass")

			logger.debug(
				"Foreground attempt %s/%s failed (fg=%s game=%s)",
				attempt, retries, fg, hwnd,
			)

		fgTitle = ""
		try:
			fgTitle = win32gui.GetWindowText(win32gui.GetForegroundWindow())
		except Exception:
			pass
		logger.error(
			"Could not focus game after %s attempts (still on %r).",
			retries, fgTitle,
		)
		return (
			"error",
			"Error",
			"Could not switch to Wuthering Waves automatically. "
			"Run Kamera as Admin, keep the game open, then press Start Scanning again.",
		)

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
