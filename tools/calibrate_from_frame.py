"""OCR probe current character ROIs against a video frame (720p capture of 1440p)."""

from __future__ import annotations

import sys
from pathlib import Path

import cv2

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.gameROI import COORDINATES
from scraping.utils.common import convertToBlackWhite, imageToString

FRAME = ROOT / "debug_out/video_frames/frame_55s.png"
# Recording is 1280x720 of a 2560x1440 game client.
REC_W, REC_H = 1280, 720
GAME_W, GAME_H = 2560, 1440


def scale_1080_to_rec(x, y, w=0, h=0):
    """Bake coords are for 1920x1080; game ran 2560x1440; recording is half of that."""
    gx = x / 1920 * GAME_W
    gy = y / 1080 * GAME_H
    gw = w / 1920 * GAME_W
    gh = h / 1080 * GAME_H
    return (
        int(gx * REC_W / GAME_W),
        int(gy * REC_H / GAME_H),
        int(gw * REC_W / GAME_W),
        int(gh * REC_H / GAME_H),
    )


def main() -> int:
    img_bgr = cv2.imread(str(FRAME))
    img = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2RGB)
    chars = COORDINATES[(16, 9)][(1920, 1080)]["characters"]
    vis = img_bgr.copy()

    for key in ("resonatorName", "resonatorLevel", "weaponName", "weaponLevel", "weaponRank"):
        c = chars[key]
        x, y, w, h = scale_1080_to_rec(c.x, c.y, c.w, c.h)
        cv2.rectangle(vis, (x, y), (x + w, y + h), (0, 0, 255), 2)
        cv2.putText(vis, key[:10], (x, max(12, y - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)
        crop = img[y : y + h, x : x + w]
        text = imageToString(convertToBlackWhite(crop), "") if crop.size else ""
        print(f"BAKED {key}@({x},{y},{w},{h}) => {text!r}")

    for key in ("leftSide", "rightSide", "skillClick", "chainClick"):
        c = chars[key]
        x, y, _, _ = scale_1080_to_rec(c.x, c.y)
        cv2.circle(vis, (x, y), 8, (0, 255, 0), 2)
        cv2.putText(vis, key[:8], (x + 10, y), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 255, 0), 1)
        print(f"CLICK {key}@({x},{y})")

    for i, c in enumerate(chars["skillPositions"]):
        x, y, _, _ = scale_1080_to_rec(c.x, c.y)
        cv2.circle(vis, (x, y), 10, (255, 0, 255), 2)
        print(f"SKILL {i}@({x},{y})")

    probes = {
        "name_a": (300, 85, 240, 36),
        "name_b": (320, 95, 260, 40),
        "level_a": (300, 125, 180, 36),
        "level_b": (280, 135, 200, 40),
        "name_wide": (250, 80, 320, 50),
        "level_wide": (250, 120, 220, 50),
    }
    for key, (x, y, w, h) in probes.items():
        cv2.rectangle(vis, (x, y), (x + w, y + h), (255, 255, 0), 1)
        crop = img[y : y + h, x : x + w]
        text = imageToString(convertToBlackWhite(crop), "") if crop.size else ""
        print(f"PROBE {key}@({x},{y},{w},{h}) => {text!r}")

    out = ROOT / "debug_out/video_frames/rois_on_55s.png"
    cv2.imwrite(str(out), vis)
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
