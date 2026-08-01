import os
import sys
import time
import signal
import logging
import multiprocessing
from datetime import datetime

from properties.config import FAILED, INVENTORY
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
	}

	if result[0] != 'error':
		time.sleep(1.2)

		completeFLAG = multiprocessing.Event()
		queue = multiprocessing.Queue()
		
		scrapersProcess = multiprocessing.Process(target=scrapers, args=(scraperEnabled, gameManager.getScreenInfo(), completeFLAG, queue, INVENTORY['date']))
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

		totalScraped = sum(scanCounts.values()) + len(INVENTORY['items'])
		if len(FAILED) > 0:
			result = ('failed', 'Failed to recognize', f'Failed to recognize {len(FAILED)} items.')
		elif totalScraped == 0:
			result = (
				'warning',
				'Nothing scanned',
				'No characters/weapons/echoes/items were recognized. '
				'Stay in English UI at 1080p/1440p; Start Scanning should leave Terminal before inventory clicks.',
			)
		else:
			result = (
				'success',
				'Complete',
				f"Scan completed: {scanCounts['characters']} characters, "
				f"{scanCounts['weapons']} weapons, {scanCounts['echoes']} echoes, "
				f"{len(INVENTORY['items'])} items.",
			)
	
	# Bring the scanner UI back after the run (or after an early error).
	WindowManager.restoreByTitle('WuWa Inventory Kamera')
	try:
		WindowManager('WuWa Inventory Kamera', 'WuWa Inventory Kamera.exe').setForeground(
			minimizeScanner=False,
		)
	except Exception:
		pass
	return result


def needToStop(tPID, completeFLAG):
	keyPress = KeyPressChecker()
	gameManager = WindowManager()

	while not completeFLAG.is_set():
		# Check if the game is no longer in the foreground or if the key is pressed
		if not gameManager.isForeground() or keyPress.isPressed():
			try:
				os.kill(tPID, signal.SIGTERM)
				logger.debug("Terminated scraper process due to key press or game not in foreground.")
			except Exception as e:
				logger.error(f"Error terminating process: {e}", exc_info=True)
			sys.exit(0)
		time.sleep(.1)

def scrapers(scraperEnabled: list, screenInfo: ScreenInfo, FLAG, queue: multiprocessing.Queue, START_DATE: str):
	try:
		controller = WindowsInputController(screenInfo.monitor)
		resonator = dict()
		inventory = dict()
		failed = list()
		weapons = list()
		echoes = list()
		achievements = list()

		for scraper in scraperEnabled:
			# Close any open panels back toward a clean state, then each scraper
			# verifies gameplay (not Terminal) before sending B/C hotkeys.
			controller.pressKey('esc', .5)
			time.sleep(0.25)

			match(scraper):
				case 'characters':
					resonator = resonatorScraper(controller, screenInfo)
				case 'weapons':
					i, w = weaponScraper(controller, screenInfo.scrapers.weapons.x, screenInfo.scrapers.weapons.y, screenInfo)
					inventory.update(i)
					weapons.extend(w)
				case 'echoes':
					echoes = echoScraper(controller, screenInfo.scrapers.echoes.x, screenInfo.scrapers.echoes.y, screenInfo)
				case 'devItems':
					i, f = itemsScraper(START_DATE, controller, screenInfo.scrapers.devItems.x, screenInfo.scrapers.devItems.y, screenInfo)
					inventory.update(i)
					failed.extend(f)
				case 'resources':
					i, f = itemsScraper(START_DATE, controller, screenInfo.scrapers.resources.x, screenInfo.scrapers.resources.y, screenInfo)
					inventory.update(i)
					failed.extend(f)
				case 'achievements':
					achievements = achievementScraper(controller, screenInfo)

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
		}

		chunkSize = 20
		inventoryItems = list(inventory.items())

		# Always report results — previously empty inventory skipped failed[] entirely
		# and the UI lied with "Scan completed without errors".
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
			# leftover failed beyond first chunk
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
