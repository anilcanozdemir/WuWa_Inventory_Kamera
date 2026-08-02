"""Capture current Resonator screen and OCR candidate name/level/header ROIs."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.foreground import WindowManager
from scraping.utils.common import convertToBlackWhite, imageToString, screenshot

OUT = ROOT / "debug_out" / f"char_rois_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


def save_rgb(path: Path, rgb) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))


def ocr(img):
    return {
        "raw": imageToString(img, ""),
        "bw": imageToString(convertToBlackWhite(img), ""),
        "raw_nospace": imageToString(img, "", bannedChars=" "),
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    wm = WindowManager()
    if wm.setForeground()[0] == "error":
        return 1
    time.sleep(0.6)
    screen = wm.getScreenInfo()
    full = screenshot(width=screen.width, height=screen.height, monitor=screen.monitor)
    save_rgb(OUT / "full.png", full)

    chars = screen.characters
    report = {
        "size": [screen.width, screen.height],
        "boxes": {
            "terminal": vars(screen.terminal),
            "name": vars(chars.resonatorName),
            "level": vars(chars.resonatorLevel),
            "leftSide": vars(chars.leftSide),
            "rightSide": vars(chars.rightSide),
        },
        "crops": {},
        "grid": [],
    }

    # Fixed config boxes
    for key, box in [
        ("header_terminal", screen.terminal),
        ("name", chars.resonatorName),
        ("level", chars.resonatorLevel),
    ]:
        crop = full[box.y : box.y + box.h, box.x : box.x + box.w]
        save_rgb(OUT / f"{key}.png", crop)
        report["crops"][key] = ocr(crop)

    # Wider header strip (Echo / Overview label)
    for y, h in [(40, 70), (40, 100), (80, 80), (100, 60)]:
        crop = full[y : y + h, 160:520]
        tag = f"header_y{y}_h{h}"
        save_rgb(OUT / f"{tag}.png", crop)
        report["crops"][tag] = ocr(crop)

    # Name / level search band on left panel
    for y in range(100, 420, 30):
        for x, w in [(200, 400), (240, 520), (260, 480)]:
            crop = full[y : y + 50, x : x + w]
            raw = imageToString(crop, "")
            bw = imageToString(convertToBlackWhite(crop), "")
            if any(ch.isalpha() for ch in (raw + bw)):
                entry = {"x": x, "y": y, "w": w, "h": 50, "raw": raw, "bw": bw}
                report["grid"].append(entry)

    (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (ROOT / "debug_out" / "_latest_char_rois.txt").write_text(str(OUT), encoding="utf-8")
    print(OUT)
    print(json.dumps({k: v for k, v in report["crops"].items()}, indent=2))
    print("grid hits", len(report["grid"]))
    for e in report["grid"][:25]:
        print(e)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
