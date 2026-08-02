import os
import sys
import time
import signal
import logging
import multiprocessing
from datetime import datetime
from pathlib import Path

from properties.config import FAILED, INVENTORY, basePATH
from scraping.utils import (
	WindowsInputController, savingScraped
)

from scraping.shellScraper import getShell
from scraping.itemsScraper import itemsScraper
from scraping.charactersScraper import resonatorScraper
from scraping.weaponsScraper import weaponScraper
from scraping.echoesScraper import echoScraper
from scraping.achievementsScraper import achievementScraper

from game.menu import MainMenuController
from game.screenInfo import ScreenInfo
from game.foreground import WindowManager
from game.stopKey import KeyPressChecker

logger = logging.getLogger('ScraperManager')

def managerStart(scraperEnabled: list):
	global INVENTORY, FAILED
	INVENTORY['date'] = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
	FAILED.clear()
	INVENTORY['items'] = dict()

	gameManager = WindowManager()
	result = MainMenuController().isInMainMenu()
	scanCounts = {
		'characters': 0,
		'weapons': 0,
		'echoes': 0,
		'items': 0,
		'achievements': 0,
		'echoExpected': 0,
		'weaponExpected': 0,
	}

	if result[0] != 'error':
		time.sleep(1.0)

		completeFLAG = multiprocessing.Event()
		queue = multiprocessing.Queue()
		
		scrapersProcess = multiprocessing.Process(
			target=scrapers,
			args=(scraperEnabled, gameManager.getScreenInfo(), completeFLAG, queue, INVENTORY['date']),
		)
		scrapersProcess.start()

		stopMonitor = multiprocessing.Process(target=needToStop, args=(scrapersProcess.pid, completeFLAG))
		stopMonitor.start()

		scrapersProcess.join()
		
		stopMonitor.terminate()
		stopMonitor.join()

		try:
			timeout = 60
			startTime = time.time()
			
			while time.time() - startTime < timeout:
				try:
					scraperResult = queue.get_nowait()
					INVENTORY['items'].update(scraperResult.get('inventory') or {})
					FAILED.extend(scraperResult.get('failed') or [])
					for key, value in (scraperResult.get('counts') or {}).items():
						if key in scanCounts:
							scanCounts[key] = max(scanCounts[key], int(value))
				except multiprocessing.queues.Empty:
					break
				except Exception as e:
					logger.error(f"Error processing queue item: {e}", exc_info=True)
					continue
			
			while True:
				try:
					queue.get_nowait()
				except:
					break
					
		except Exception as e:
			logger.error(f"Fatal error processing queue: {e}", exc_info=True)
			WindowManager.restoreByTitle('WuWa Inventory Kamera')
			return ('failed', 'Queue processing error', str(e))
		finally:
			queue.close()
			queue.join_thread()

		savingScraped(START_DATE=INVENTORY['date'])

		# Shell credit 0 is not a real scan result.
		meaningfulItems = {
			k: v for k, v in INVENTORY['items'].items()
			if not (str(k) == '2' and not v)
		}
		totalScraped = (
			scanCounts['characters']
			+ scanCounts['weapons']
			+ scanCounts['echoes']
			+ scanCounts['achievements']
			+ len(meaningfulItems)
		)
		logger.info("Scan counts=%s items=%s failed=%s", scanCounts, len(meaningfulItems), len(FAILED))

		shortfalls = []
		echoExpected = int(scanCounts.get('echoExpected') or 0)
		weaponExpected = int(scanCounts.get('weaponExpected') or 0)
		if echoExpected and scanCounts['echoes'] < echoExpected:
			shortfalls.append(f"echoes {scanCounts['echoes']}/{echoExpected}")
		if weaponExpected and scanCounts['weapons'] < weaponExpected:
			shortfalls.append(f"weapons {scanCounts['weapons']}/{weaponExpected}")

		if len(FAILED) > 0:
			result = ('failed', 'Failed to recognize', f'Failed to recognize {len(FAILED)} items.')
		elif totalScraped == 0:
			result = (
				'warning',
				'Nothing scanned',
				'No resonators/weapons/echoes/items were recognized. '
				'Check logs/scraper-child.log. Prefer only Characters first.',
			)
		elif shortfalls:
			result = (
				'warning',
				'Incomplete scan',
				'Shortfall: ' + ', '.join(shortfalls) + '. '
				f"Got {scanCounts['characters']} characters, "
				f"{scanCounts['weapons']} weapons, {scanCounts['echoes']} echoes.",
			)
		else:
			result = (
				'success',
				'Complete',
				f"Scan completed: {scanCounts['characters']} characters, "
				f"{scanCounts['weapons']} weapons, {scanCounts['echoes']} echoes, "
				f"{len(meaningfulItems)} items.",
			)
	
	WindowManager.restoreByTitle('WuWa Inventory Kamera')
	try:
		WindowManager('WuWa Inventory Kamera', 'WuWa Inventory Kamera.exe').setForeground(
			minimizeScanner=False,
		)
	except Exception:
		pass
	return result


def needToStop(tPID, completeFLAG):
	"""Cancel only on ENTER. Do NOT kill on focus loss — that aborted real scans."""
	keyPress = KeyPressChecker()

	while not completeFLAG.is_set():
		if keyPress.isPressed():
			try:
				os.kill(tPID, signal.SIGTERM)
				logging.getLogger('ScraperManager').debug(
					"Terminated scraper process because ENTER was pressed."
				)
			except Exception as e:
				logging.getLogger('ScraperManager').error(
					f"Error terminating process: {e}", exc_info=True
				)
			sys.exit(0)
		time.sleep(0.1)


def _configureChildLogging():
	logDir = Path(basePATH) / 'logs'
	logDir.mkdir(parents=True, exist_ok=True)
	logFile = logDir / 'scraper-child.log'
	root = logging.getLogger()
	root.setLevel(logging.DEBUG)
	# Avoid duplicate handlers if re-run in-process
	if not any(isinstance(h, logging.FileHandler) and getattr(h, 'baseFilename', '').endswith('scraper-child.log') for h in root.handlers):
		fh = logging.FileHandler(logFile, encoding='utf-8', mode='w')
		fh.setFormatter(logging.Formatter('%(asctime)s|%(levelname)s|%(name)s|%(message)s'))
		root.addHandler(fh)
	return logFile


def scrapers(scraperEnabled: list, screenInfo: ScreenInfo, FLAG, queue: multiprocessing.Queue, START_DATE: str):
	try:
		logFile = _configureChildLogging()
		logger.info("Child scraper started enabled=%s log=%s", scraperEnabled, logFile)

		controller = WindowsInputController(screenInfo.monitor)
		menu = MainMenuController()
		resonator = dict()
		inventory = dict()
		failed = list()
		weapons = list()
		echoes = list()
		achievements = list()
		echoExpected = 0
		weaponExpected = 0

		for scraper in scraperEnabled:
			logger.info("Running scraper: %s", scraper)

			# Characters can open from the Terminal Resonators tile. Other scrapers
			# need gameplay + inventory hotkeys. Overview is not Terminal, so always
			# ESC out of character UI before backpack scrapers.
			if scraper != 'characters':
				for _ in range(3):
					controller.pressKey('esc', 0.4)
					time.sleep(0.35)
					if menu.isMenu():
						break
				if menu.isMenu() and not menu.ensureGameplay(controller, maxEscapes=3):
					logger.error("Could not leave Terminal before %s — skipping", scraper)
					continue
			elif scraper != scraperEnabled[0]:
				# Returning to Terminal/game between scrapers
				controller.pressKey('esc', 0.45)
				time.sleep(0.35)

			match(scraper):
				case 'characters':
					resonator = resonatorScraper(controller, screenInfo)
					logger.info("Characters scraped: %s", len(resonator))
				case 'weapons':
					i, w, weaponExpected = weaponScraper(controller, screenInfo.scrapers.weapons.x, screenInfo.scrapers.weapons.y, screenInfo)
					inventory.update(i)
					weapons.extend(w)
					logger.info("Weapons scraped: %s (expected %s)", len(weapons), weaponExpected)
				case 'echoes':
					echoes, echoExpected = echoScraper(controller, screenInfo.scrapers.echoes.x, screenInfo.scrapers.echoes.y, screenInfo)
					logger.info("Echoes scraped: %s (expected %s)", len(echoes), echoExpected)
				case 'devItems':
					i, f = itemsScraper(START_DATE, controller, screenInfo.scrapers.devItems.x, screenInfo.scrapers.devItems.y, screenInfo)
					inventory.update(i)
					failed.extend(f)
					logger.info("Dev items scraped: %s failed=%s", len(i), len(f))
				case 'resources':
					i, f = itemsScraper(START_DATE, controller, screenInfo.scrapers.resources.x, screenInfo.scrapers.resources.y, screenInfo)
					inventory.update(i)
					failed.extend(f)
					logger.info("Resources scraped: %s failed=%s", len(i), len(f))
				case 'achievements':
					achievements = achievementScraper(controller, screenInfo)
					logger.info("Achievements scraped: %s", len(achievements))

			if scraper not in ['characters', 'achievements']:
				if '2' not in inventory or inventory.get('2') == 0:
					shell = getShell(screenInfo)
					inventory = {**shell, **inventory}

		controller.pressKey('esc')

		counts = {
			'characters': len(resonator),
			'weapons': len(weapons),
			'echoes': len(echoes),
			'items': len(inventory),
			'achievements': len(achievements),
			'echoExpected': echoExpected,
			'weaponExpected': weaponExpected,
		}
		logger.info("Finished scrapers counts=%s", counts)

		chunkSize = 20
		inventoryItems = list(inventory.items())

		if not inventoryItems:
			queue.put({
				'inventory': {},
				'failed': failed,
				'counts': counts,
			})
		else:
			for i in range(0, len(inventoryItems), chunkSize):
				chunk = dict(inventoryItems[i:i + chunkSize])
				queue.put({
					'inventory': chunk,
					'failed': failed[i:i + chunkSize] if i == 0 else [],
					'counts': counts if i == 0 else {},
				})
			if len(failed) > chunkSize:
				queue.put({
					'inventory': {},
					'failed': failed[chunkSize:],
					'counts': {},
				})
			
		FLAG.set()
		savingScraped({
			'characters_wuwainventorykamera.json': (resonator, dict),
			'weapons_wuwainventorykamera.json': (weapons, list),
			'echoes_wuwainventorykamera.json': (echoes, list),
			'achievements_wuwainventorykamera.json': (achievements, list),
		}, START_DATE)

	except Exception as e:
		FLAG.set()
		logger.error(f"Error in scrapers: {e}", exc_info=True)
		queue.put({
			'inventory': {},
			'failed': [],
			'counts': {},
		})
