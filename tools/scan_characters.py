"""Elevated characters-only scan for debugging the resonator roster loop.

Run with the game open (Terminal or gameplay; Echo/Overview also OK if C opens roster):
  Start-Process .\\.venv\\Scripts\\python.exe -Verb RunAs `
    -ArgumentList 'tools\\scan_characters.py' -WorkingDirectory (Get-Location)

Abort with F12. Writes debug_out/characters_*/report.json + export.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ABORT_KEY_VK = 0x7B


def hideConsole() -> None:
    try:
        import win32con
        import win32gui
        from ctypes import windll

        hwnd = windll.kernel32.GetConsoleWindow()
        if hwnd:
            win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
    except Exception:
        pass


EXPECTED = 20
print("Characters scan starting. F12 aborts.", flush=True)
print(
    f"Expect ~{EXPECTED} resonators with Weapon / Forte / Chain / Echo details. "
    "This takes a while (~20–30 min). Console stays open.",
    flush=True,
)
# Keep console visible — minimized window made it look like it never ends.
STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / "debug_out" / f"characters_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[
        logging.FileHandler(OUT / "scan.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
# Console: INFO+ only; full DEBUG stays in the log file.
logging.getLogger().handlers[-1].setLevel(logging.INFO)
log = logging.getLogger("scan_characters")


def watchAbort() -> None:
    import win32api

    while win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
        time.sleep(0.05)
    time.sleep(0.4)
    while True:
        if win32api.GetAsyncKeyState(ABORT_KEY_VK) & 0x8000:
            log.warning("F12 abort")
            logging.shutdown()
            os._exit(3)
        time.sleep(0.05)


def main() -> int:
    threading.Thread(target=watchAbort, daemon=True).start()

    from game.foreground import WindowManager
    from game.menu import MainMenuController
    from properties.config import cfg
    from scraping.charactersScraper import resonatorScraper
    from scraping.utils import WindowsInputController, charactersID, savingScraped

    manager = WindowManager()
    status = manager.setForeground()
    log.info("focus=%s", status)
    if status[0] == "error":
        return 2

    time.sleep(1.0)
    screen = manager.getScreenInfo()
    controller = WindowsInputController(screen.monitor)
    menu = MainMenuController()

    # Close bag if open so Terminal/Overview OCR is clean.
    if not menu.isMenu():
        from scraping.utils import imageToString, screenshot
        import string

        page = screen.weapons.page
        probe = screenshot(int(page.x), int(page.y), int(page.w), int(page.h), monitor=screen.monitor)
        if "/" in imageToString(probe, allowedChars=string.digits + "/"):
            log.info("Inventory open — ESC")
            controller.pressKey("esc", 0.6)
            time.sleep(0.5)

    started = time.time()
    print(f"Scanning… log: {OUT / 'scan.log'}", flush=True)

    import scraping.charactersScraper as cs

    # Full roster details (one-char smoke already validated these paths).
    cs.SCRAPE_WEAPON = True
    cs.SCRAPE_SKILLS = True
    cs.SCRAPE_CHAIN = True
    cs.SCRAPE_ECHOES = True

    characters = resonatorScraper(controller, screen, expectedCount=EXPECTED)
    elapsed = round(time.time() - started, 1)
    print(f"Finished in {elapsed}s — {len(characters)}/{EXPECTED} resonators", flush=True)

    # Map known IDs back to canonical names for the report.
    id_to_name = {v: k for k, v in charactersID.items()}
    roster = []
    for rid, data in characters.items():
        try:
            nid = int(rid) if not isinstance(rid, int) and str(rid).isdigit() else rid
        except Exception:
            nid = rid
        skills = dict(data.get("skills") or {})
        skill_fmt = (
            f"{int(skills.get('normal') or 0)}/"
            f"{int(skills.get('resonance') or 0)}({int(skills.get('stats1') or 0)})/"
            f"{int(skills.get('forte') or 0)}({int(skills.get('inherent') or 0)})/"
            f"{int(skills.get('liberation') or 0)}({int(skills.get('stats3') or 0)})/"
            f"{int(skills.get('intro') or 0)}"
        )
        roster.append(
            {
                "id": rid,
                "canonical": id_to_name.get(nid) or id_to_name.get(rid),
                "level": data.get("level"),
                "ascension": data.get("ascension"),
                "weapon": dict(data.get("weapon") or {}),
                "skills": skills,
                "skills_fmt": skill_fmt,
                "chain": data.get("chain"),
                "echoes": dict(data.get("echoes") or {}),
            }
        )

    date = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    savingScraped(
        {"characters_wuwainventorykamera.json": (characters, dict)},
        date,
    )

    report = {
        "elapsed_s": elapsed,
        "export": str(Path(cfg.get(cfg.exportFolder)) / date),
        "roverName_cfg": cfg.get(cfg.roverName),
        "count": len(characters),
        "expected_count": EXPECTED,
        "ok_count": len(characters) == EXPECTED,
        "roster": roster,
        "flags": {
            "scrape_weapon": True,
            "scrape_skills": True,
            "scrape_chain": True,
            "scrape_echoes": True,
        },
        "luuk_ground_truth": {
            "id": 1305,
            "expect_skills_fmt": "4/8(1)/8(1)/8(2)/1",
            "expect_weapon_id": 21040056,
            "expect_weapon_level": 80,
            "expect_chain": 0,
            "expect_echo_count": 5,
        },
    }

    # Validate Luuk / Xiangli Yao if present.
    luuk = next((r for r in roster if str(r.get("id")) in ("1305",) or r.get("canonical") == "xiangliyao"), None)
    if luuk:
        wid = (luuk.get("weapon") or {}).get("id")
        echoes = luuk.get("echoes") or {}
        report["luuk_checks"] = {
            "skills_fmt_ok": luuk.get("skills_fmt") == "4/8(1)/8(1)/8(2)/1",
            "weapon_ok": wid in (21040056, "21040056") or str(wid) == "21040056",
            "weapon_level_ok": int((luuk.get("weapon") or {}).get("level") or 0) == 80,
            "chain_ok": int(luuk.get("chain") or 0) == 0,
            "echo_count_ok": len(echoes) == 5,
            "echo_sonata_ok": all(bool((e or {}).get("sonata")) for e in echoes.values()) if echoes else False,
        }
        print(f"LUUK checks: {report['luuk_checks']}", flush=True)

    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (ROOT / "debug_out" / "_latest_characters.txt").write_text(str(OUT), encoding="utf-8")
    log.info("DONE count=%s ok=%s export=%s", len(characters), report["ok_count"], report["export"])
    return 0 if characters else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        log.exception("scan crashed")
        raise SystemExit(1)
