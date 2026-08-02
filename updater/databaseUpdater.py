import re
import json
import shutil
import urllib.request
import logging
from babel import Locale
from pathlib import Path
from dataclasses import dataclass
from PySide6.QtCore import QObject, Signal

from properties.config import cfg
from scraping.utils import (
	itemsID, charactersID, characterAliases, weaponsID,
	echoesID, achievementsID, echoStats,
	definedText, sonataName
)

logger = logging.getLogger('DatabaseManager')

@dataclass
class FileConfig:
	folder: list[str]
	file: str

class DataUpdater(QObject):
	updateProgress = Signal(int, str)
	updateFinished = Signal()

	API = 'https://api.github.com/repos/{owner}/{repo}/contents/{path}'
	
	def __init__(self):
		super().__init__()
		self.author = 'Dimbreath'
		self.repo = 'WutheringData'
		self.lang = self._getLanguage()
		self.files = [
			FileConfig(['TextMap', self.lang], 'MultiText.json'),
			FileConfig(['ConfigDB'], 'ItemInfo.json'),
			FileConfig(['ConfigDB'], 'WeaponConf.json'),
		]
		self.updated = False

	def _getLanguage(self) -> str:
		self.makeFolder()

		url = self.API.format(
			owner=self.author,
			repo=self.repo,
			path='TextMap'
		)
		uLang = cfg.get(cfg.gameLanguage)
		languages = self.loadJson('languages.json')
		
		if uLang not in languages:
			languages = {self._getLanguageName(item['name']): item['name'] for item in self.fetchFileData(url) if item['type'] == 'dir'}
			self.saveJson(languages, 'languages.json')

		return languages.get(uLang, 'en')

	def makeFolder(self):
		Path('data').mkdir(parents=True, exist_ok=True)
		logger.debug("Ensured 'data' directory exists.")

	def _getLanguageName(self, code: str) -> str:
		parts = code.split('-')
		locale = Locale(parts[0], script=parts[1] if len(parts) != 1 else None)
		try: return locale.get_display_name().capitalize()
		except: return code

	def fetchFileData(self, url: str) -> dict:
		try:
			with urllib.request.urlopen(urllib.request.Request(url)) as response:
				return json.loads(response.read().decode())
		except:
			return {}

	def updateFiles(self):
		for fileConfig in self.files:
			url = self.API.format(
				owner=self.author,
				repo=self.repo,
				path='/'.join(fileConfig.folder + [fileConfig.file])
			)

			logger.info(f'Checking for updates on file: {fileConfig.file}')
			try:
				data = self.fetchFileData(url)
				filePath: Path = Path('data') / fileConfig.file

				currentSize = filePath.stat().st_size if filePath.is_file() else 0

				if data['size'] != currentSize:
					logger.info(f'Downloading updated version of {fileConfig.file}...')
					urllib.request.urlretrieve(
						data['download_url'],
						filePath,
						reporthook=lambda block_num, block_size, total_size: self.reportProgress(fileConfig.file, block_num, block_size, total_size)
					)
					self.updated = True
					logger.info(f'File updated: {fileConfig.file}')
			except Exception as e:
				logger.error(f'Failed to update {fileConfig.file}. Error: {e}')
	
	
	def reportProgress(self, file_name, block_num, block_size, total_size):
		downloaded = block_num * block_size
		percent = (downloaded / total_size)*100
		self.updateProgress.emit(percent, file_name)

	def loadJson(self, filename: str) -> dict:
		try:
			with open(f'./data/{filename}', 'r', encoding='utf-8') as f:
				return json.load(f)
		except:
			return dict()

	def saveJson(self, data: dict, filename: str):
		with open(f'./data/{filename}', 'w', encoding='utf-8') as f:
			json.dump(data, f, indent=4)

	def _loadExtras(self, filename: str) -> dict:
		extra = {}
		for path in (
			Path(__file__).resolve().parent / filename,
			Path('data') / filename,
		):
			try:
				payload = json.loads(path.read_text(encoding='utf-8'))
			except (FileNotFoundError, json.JSONDecodeError, OSError):
				continue
			if isinstance(payload, dict):
				extra.update(payload)
		return extra

	def _mergeItemExtras(self, data: dict, filename: str) -> int:
		"""Merge hand-curated id/name entries (Dimbreath lag). Returns added count."""
		extra = self._loadExtras(filename)
		added = 0
		for key, value in extra.items():
			if key.startswith('_') or not isinstance(value, dict):
				continue
			itemId = value.get('id')
			if itemId is None:
				continue
			entry = dict(value)
			entry.setdefault('name', key)
			if key not in data:
				added += 1
			data[key] = {**data.get(key, {}), **entry}
		return added

	def updateItems(self, forceRebuild: bool = False):
		itemsPath = Path('data') / 'items.json'
		weaponsPath = Path('data') / 'weapons.json'
		shouldRebuild = forceRebuild or self.updated or (not itemsPath.is_file()) or (not weaponsPath.is_file())

		try:
			if shouldRebuild:
				logger.info('Updating items.json / weapons.json from MultiText...')
				infoText = self.loadJson('MultiText.json')
				itemInfo = self.loadJson('ItemInfo.json')
				weaponInfo = self.loadJson('WeaponConf.json')
				if not infoText or not itemInfo:
					raise ValueError('MultiText/ItemInfo missing; cannot rebuild items')

				items = {}
				for item in itemInfo:
					if item['Name'] not in infoText:
						continue
					key = infoText[item['Name']].lower().replace(' ', '')
					icon = item.get('Icon') or ''
					image = (
						icon.split('/Image/')[1].rsplit('.', 1)[0] + '.png'
						if '/Image/' in icon else ''
					)
					items[key] = {
						'id': item['Id'],
						'name': infoText[item['Name']],
						'image': image,
					}

				weapons = {}
				for weapon in weaponInfo:
					if weapon['WeaponName'] not in infoText:
						continue
					key = infoText[weapon['WeaponName']].lower().replace(' ', '')
					icon = weapon.get('Icon') or ''
					image = (
						icon.split('/Image/')[1].rsplit('.', 1)[0] + '.png'
						if '/Image/' in icon else ''
					)
					weapons[key] = {
						'id': weapon['ModelId'],
						'name': infoText[weapon['WeaponName']],
						'rarity': weapon['QualityId'],
						'image': image,
					}
			else:
				items = self.loadJson('items.json')
				weapons = self.loadJson('weapons.json')

			addedItems = self._mergeItemExtras(items, 'items_extra.json')
			addedWeapons = self._mergeItemExtras(weapons, 'weapons_extra.json')
			if addedItems:
				logger.info('Merged %s entries from items_extra.json', addedItems)
			if addedWeapons:
				logger.info('Merged %s entries from weapons_extra.json', addedWeapons)

			self.saveJson(items, 'items.json')
			self.saveJson(weapons, 'weapons.json')
			itemsID.clear()
			itemsID.update(items)
			weaponsID.clear()
			weaponsID.update(weapons)

		except Exception as e:
			logger.error(f'Failed to update items.json. Error: {e}', exc_info=True)

	def updateJsonFromPattern(self, fileName: str, pattern: str, transformFunc):
		logger.info(f'Updating {fileName}...')
		try:
			infoText = self.loadJson('MultiText.json')
			
			data = {}
			compiledPattern = re.compile(pattern)
			for key in infoText:
				if match := compiledPattern.match(key):
					transformed = transformFunc(infoText[key], match)
					if transformed is not None:
						data[transformed] = int(match.group(1))

			self.saveJson(data, fileName)
			return data
		except Exception as e:
			logger.error(f'Failed to update {fileName}. Error: {e}', exc_info=True)

	def updateCharacters(self):
		data = self.updateJsonFromPattern(
			'characters.json',
			r'^RoleInfo_(\d+)_Name$',
			lambda text, match: text.lower().replace(' ', '') if int(match.group(1)) < 5000 else None
		)
		# Dimbreath MultiText lags live client for new SP forms (Yangyang: Xuanling 1610).
		extra = {}
		for path in (
			Path(__file__).resolve().parent / 'characters_extra.json',
			Path('data') / 'characters_extra.json',
		):
			try:
				payload = json.loads(path.read_text(encoding='utf-8'))
			except (FileNotFoundError, json.JSONDecodeError, OSError):
				continue
			extra.update(payload)
		if data is None:
			data = self.loadJson('characters.json')
		added = 0
		for key, value in extra.items():
			if key.startswith('_') or not isinstance(value, int):
				continue
			if key not in data:
				added += 1
			data[key] = value
		if added:
			logger.info('Merged %s entries from characters_extra.json', added)
		self.saveJson(data, 'characters.json')
		if data:
			charactersID.clear()
			charactersID.update(data)

	def updateEcho(self):
		data = self.updateJsonFromPattern(
			'echoes.json',
			r'^MonsterInfo_(\d+)_Name$',
			lambda text, match: text.lower().replace(' ', '') if int(match.group(1)) < 350000000 else None
		)
		# Dimbreath MultiText lags the live client; merge hand-curated IDs so
		# newly released echoes (e.g. Forbidden Bastion) are not scanned as misses.
		# Bundled extras live next to this module (data/ is gitignored).
		extra = {}
		for path in (
			Path(__file__).resolve().parent / 'echoes_extra.json',
			Path('data') / 'echoes_extra.json',
		):
			try:
				payload = json.loads(path.read_text(encoding='utf-8'))
			except (FileNotFoundError, json.JSONDecodeError, OSError):
				continue
			extra.update(payload)
		added = 0
		if data is None:
			data = self.loadJson('echoes.json')
		for key, value in extra.items():
			if key.startswith('_') or not isinstance(value, int):
				continue
			if key not in data:
				added += 1
			data[key] = value
		if added:
			logger.info('Merged %s entries from echoes_extra.json', added)
		self.saveJson(data, 'echoes.json')
		if data:
			echoesID.clear()
			echoesID.update(data)

	def updateAchievements(self):
		data = self.updateJsonFromPattern(
			'achievements.json',
			r'^Achievement_(\d+)_Name$',
			lambda text, _: text
		)
		if data:
			achievementsID.update(data)

	def updateEchoStats(self):
		statsKey = {
			'PropertyIndex_10003_Name': 'hp',
			'PropertyIndex_10007_Name': 'atk',
			'PropertyIndex_10008_Name': 'cr',
			'PropertyIndex_10009_Name': 'cd',
			'PropertyIndex_10010_Name': 'def',
			'PropertyIndex_10011_Name': 'er',
			'PropertyIndex_10014_Name': 'skillDmg',
			'PropertyIndex_10017_Name': 'basicAttack',
			'PropertyIndex_10018_Name': 'heavyAttack',
			'PropertyIndex_10019_Name': 'liberationDmg',
			'PropertyIndex_10022_Name': 'glacio',
			'PropertyIndex_10023_Name': 'fusion',
			'PropertyIndex_10024_Name': 'electro',
			'PropertyIndex_10025_Name': 'aero',
			'PropertyIndex_10026_Name': 'spectro',
			'PropertyIndex_10027_Name': 'havoc',
			'PropertyIndex_10035_Name': 'healing'
		}

		try:
			infoText = self.loadJson('MultiText.json')
			
			stats = {infoText[key].lower().replace(' ', '').replace('.', ''): value
					 for key, value in statsKey.items()}
			
			self.saveJson(stats, 'echoStats.json')
			echoStats.update(stats)
			
		except Exception as e:
			logger.error(f'Failed to update echoStats. Error: {e}', exc_info=True)

	def updateSonata(self):
		data = self.updateJsonFromPattern(
			'sonataName.json',
			r'^PhantomFetter_(\d+)_Name$',
			lambda text, _: text.lower().replace(' ', '')
		)
		extra = {}
		for path in (
			Path(__file__).resolve().parent / 'sonata_extra.json',
			Path('data') / 'sonata_extra.json',
		):
			try:
				payload = json.loads(path.read_text(encoding='utf-8'))
			except (FileNotFoundError, json.JSONDecodeError, OSError):
				continue
			extra.update(payload)
		if data is None:
			try:
				data = self.loadJson('sonataName.json')
			except Exception:
				data = {}
		if not isinstance(data, dict):
			data = {}
		added = 0
		for key, value in extra.items():
			if key.startswith('_') or not isinstance(value, int):
				continue
			if key not in data:
				added += 1
			data[key] = value
		if added:
			logger.info('Merged %s entries from sonata_extra.json', added)
		if data:
			self.saveJson(data, 'sonataName.json')
			sonataName.clear()
			sonataName.extend(list(data))

	def installSidecars(self):
		"""Copy gitignored calib/alias JSON from the updater package into ./data."""
		Path('data').mkdir(parents=True, exist_ok=True)
		here = Path(__file__).resolve().parent
		for name in ('character_aliases.json', 'roster_page_jump.json'):
			src = here / name
			dst = Path('data') / name
			if not src.is_file():
				continue
			try:
				if (not dst.is_file()) or (src.stat().st_mtime > dst.stat().st_mtime):
					shutil.copy2(src, dst)
					logger.info('Installed sidecar %s', name)
			except OSError:
				logger.debug('Failed installing sidecar %s', name, exc_info=True)
		aliasPath = Path('data') / 'character_aliases.json'
		if aliasPath.is_file():
			try:
				payload = json.loads(aliasPath.read_text(encoding='utf-8'))
				if isinstance(payload, dict):
					characterAliases.clear()
					characterAliases.update({
						str(k): v for k, v in payload.items() if not str(k).startswith('_')
					})
			except (json.JSONDecodeError, OSError):
				logger.debug('Failed reloading character_aliases.json', exc_info=True)

	def updateDefinedText(self):
		textKey = [
			'PrefabTextItem_1547656443_Text',  # Terminal
			'PrefabTextItem_128820487_Text',   # Claim
			'PrefabTextItem_3963945691_Text'   # Activated
		]

		try:
			infoText = self.loadJson('MultiText.json')
			
			stats = {key: infoText[key].lower().replace(' ', '').replace('-', '').strip()
					 for key in textKey}
			
			self.saveJson(stats, 'definedText.json')
			definedText.update(stats)
			
		except Exception as e:
			logger.error(f'Failed to update definedText. Error: {e}', exc_info=True)

	def run(self):
		self.installSidecars()
		self.updateFiles()
		if self.updated:
			self.updateItems(forceRebuild=True)
			self.updateEchoStats()
			self.updateSonata()
			self.updateDefinedText()
			self.updateAchievements()
			self.updateCharacters()
			self.updateEcho()
		else:
			try:
				# Still merge hand-curated extras when Dimbreath files are unchanged.
				self.updateItems(forceRebuild=False)
				self.updateCharacters()
				self.updateEcho()
				self.updateSonata()
			except Exception:
				logger.debug('Extra merge without MultiText refresh failed', exc_info=True)
			self.installSidecars()
		self.updateFinished.emit()
