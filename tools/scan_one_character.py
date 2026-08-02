"""Smoke-test one selected resonator using upstream Psycho-Marcus section loop.

Open Resonators → Overview, select Luuk, then run:
  tools\\START_ONE_CHAR.bat

Does NOT walk the roster. Does NOT discover tabs (that was re-opening Weapon).
Abort with F12. Writes debug_out/one_char_*/report.json
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

STAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT = ROOT / "debug_out" / f"one_char_{STAMP}"
OUT.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s|%(levelname)s|%(name)s|%(message)s",
    handlers=[
        logging.FileHandler(OUT / "scan.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("one_char")


def _watchAbort() -> None:
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


def _emptyOne() -> dict:
    from scraping.charactersScraper import _emptyCharacters
    return _emptyCharacters()


def main() -> int:
    print("ONE-CHAR (upstream loop). Select Luuk on Overview. F12 aborts.", flush=True)
    threading.Thread(target=_watchAbort, daemon=True).start()

    from game.foreground import WindowManager
    from scraping.charactersScraper import (
        ensureResonatorOverview,
        isOnResonatorScreen,
        scrapeCharacterDetails,
        scrapeResonator,
    )
    from scraping.utils import charactersID
    from scraping.utils.common import screenshot
    from scraping.utils.mouse_keyboard import WindowsInputController

    wm = WindowManager()
    if wm.setForeground()[0] == "error":
        log.error("Game window not found")
        return 1
    time.sleep(0.5)
    screen = wm.getScreenInfo()
    controller = WindowsInputController(screen.monitor)

    if not isOnResonatorScreen(screen):
        log.error("Not on Resonator — open Overview and select Luuk first")
        return 1
    if not ensureResonatorOverview(controller, screen):
        log.error("Could not reach Overview")
        return 1

    characters = _emptyOne()
    cache: dict = {}
    image = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    rid, _ = scrapeResonator(image, screen, characters, cache)
    if not rid:
        log.error("Could not OCR selected resonator — stay on Overview with Luuk selected")
        return 1

    id_to_name = {v: k for k, v in charactersID.items()}
    canonical = id_to_name.get(rid) or id_to_name.get(int(rid) if str(rid).isdigit() else rid)
    print(f"Selected: {canonical or rid} (id={rid}) — upstream sections…", flush=True)
    log.info("Selected rid=%s canonical=%s level=%s", rid, canonical, characters[rid].get("level"))

    t0 = time.time()
    # Upstream: Weapon → (Echo skip) → Forte → Chain. No tab discover.
    scrapeCharacterDetails(
        controller,
        screen,
        characters,
        rid,
        cache,
        do_weapon=True,
        do_skills=True,
        do_chain=True,
        do_echoes=True,
    )
    elapsed = round(time.time() - t0, 1)

    data = characters[rid]
    skills = dict(data.get("skills") or {})
    # Display like: 4/8(1)/8(1)/8(2)/1
    skill_fmt = (
        f"{int(skills.get('normal') or 0)}/"
        f"{int(skills.get('resonance') or 0)}({int(skills.get('stats1') or 0)})/"
        f"{int(skills.get('forte') or 0)}({int(skills.get('inherent') or 0)})/"
        f"{int(skills.get('liberation') or 0)}({int(skills.get('stats3') or 0)})/"
        f"{int(skills.get('intro') or 0)}"
    )
    report = {
        "elapsed_s": elapsed,
        "out": str(OUT),
        "id": rid,
        "canonical": canonical,
        "level": data.get("level"),
        "ascension": data.get("ascension"),
        "weapon": dict(data.get("weapon") or {}),
        "skills": skills,
        "skills_fmt": skill_fmt,
        "chain": data.get("chain"),
        "echoes": dict(data.get("echoes") or {}),
        # Luuk: Normal 4 / Resonance 8(1) / Forte 8(1) / Liberation 8(2) / Intro 1
        "luuk_ground_truth": {
            "expect_skills_fmt": "4/8(1)/8(1)/8(2)/1",
            "expect_normal": 4,
            "expect_resonance": 8,
            "expect_stats1": 1,
            "expect_forte": 8,
            "expect_inherent": 1,
            "expect_liberation": 8,
            "expect_stats3": 2,
            "expect_intro": 1,
            "expect_weapon_id": 21040056,
            "expect_weapon_key": "daybreaker'sspine",
            "expect_weapon_level": 80,
            "expect_weapon_ascension": 5,  # cap 80 → index in ASCENSION_LEVELS
            "expect_chain": 0,
        },
    }
    if str(rid) == "1305" or rid == 1305:
        wid = report["weapon"].get("id")
        report["luuk_checks"] = {
            "skills_fmt_ok": skill_fmt == "4/8(1)/8(1)/8(2)/1",
            "normal_ok": int(skills.get("normal") or 0) == 4,
            "resonance_ok": int(skills.get("resonance") or 0) == 8,
            "stats1_ok": int(skills.get("stats1") or 0) == 1,
            "forte_ok": int(skills.get("forte") or 0) == 8,
            "inherent_ok": int(skills.get("inherent") or 0) == 1,
            "liberation_ok": int(skills.get("liberation") or 0) == 8,
            "stats3_ok": int(skills.get("stats3") or 0) == 2,
            "intro_ok": int(skills.get("intro") or 0) == 1,
            "weapon_ok": wid in (21040056, "21040056") or str(wid) == "21040056",
            "weapon_level_ok": int(report["weapon"].get("level") or 0) == 80,
            "weapon_ascension_ok": int(report["weapon"].get("ascension") or -1) == 5,
            "chain_ok": int(data.get("chain") or 0) == 0,
        }
        print(f"skills_fmt={skill_fmt}  expect=4/8(1)/8(1)/8(2)/1", flush=True)
        print(f"LUUK checks: {report['luuk_checks']}", flush=True)

    (OUT / "report.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    (ROOT / "debug_out" / "_latest_one_char.txt").write_text(str(OUT), encoding="utf-8")
    print(json.dumps(report, indent=2, default=str), flush=True)
    print(f"DONE in {elapsed}s → {OUT}", flush=True)
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        log.exception("one_char failed")
        raise SystemExit(1)
