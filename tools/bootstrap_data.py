"""
Download / build the runtime data/ files without launching the Qt UI.

Usage:
  .\\.venv\\Scripts\\python.exe tools\\bootstrap_data.py
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from updater.databaseUpdater import DataUpdater


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    )
    updater = DataUpdater()
    # Force rebuild of derived JSON even when size matches
    updater.updated = True
    updater.updateFiles()
    updater.updated = True
    updater.updateItems()
    updater.updateEchoStats()
    updater.updateSonata()
    updater.updateDefinedText()
    updater.updateAchievements()
    updater.updateCharacters()
    updater.updateEcho()
    defined = Path("data/definedText.json")
    print(f"definedText exists={defined.is_file()} path={defined.resolve()}")
    if defined.is_file():
        print(defined.read_text(encoding="utf-8"))
    return 0 if defined.is_file() else 1


if __name__ == "__main__":
    raise SystemExit(main())
