"""Measure Forte skill/node positions from a screenshot (scaled or native)."""
from __future__ import annotations

import cv2
import numpy as np
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SHOT = ROOT / "debug_out" / "forte_calib" / "forte_full.png"
OUT = ROOT / "debug_out" / "forte_calib"


def main() -> None:
    img = cv2.imread(str(SHOT))
    h, w = img.shape[:2]
    scale = 2560 / w
    print(f"shot={w}x{h} scale_to_1440={scale:.3f}")

    vis = img.copy()
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Exclude left rail / right roster
    x0, x1 = int(0.08 * w), int(0.86 * w)
    y0, y1 = int(0.25 * h), int(0.92 * h)
    roi = gray[y0:y1, x0:x1]
    blur = cv2.GaussianBlur(roi, (5, 5), 0)

    circles = cv2.HoughCircles(
        blur,
        cv2.HOUGH_GRADIENT,
        dp=1.15,
        minDist=14,
        param1=70,
        param2=16,
        minRadius=6,
        maxRadius=22,
    )
    pts: list[tuple[int, int, int, str]] = []
    if circles is not None:
        for x, y, r in np.round(circles[0]).astype(int):
            ax, ay = int(x + x0), int(y + y0)
            pts.append((ax, ay, int(r), "c"))
            cv2.circle(vis, (ax, ay), int(r), (0, 255, 0), 1)

    # Bright local maxima for diamond skills (larger, lower band)
    band_y0, band_y1 = int(0.55 * h), int(0.88 * h)
    band = gray[band_y0:band_y1, x0:x1]
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (21, 21))
    dil = cv2.dilate(band, ker)
    msk = (band == dil) & (band > 95)
    ys, xs = np.where(msk)
    # take top brightness peaks, spaced
    peaks = sorted(((int(band[y, x]), int(x + x0), int(y + band_y0)) for x, y in zip(xs, ys)), reverse=True)
    diamonds: list[tuple[int, int]] = []
    for bri, ax, ay in peaks:
        if bri < 100:
            break
        if any(abs(ax - px) < 25 and abs(ay - py) < 25 for px, py in diamonds):
            continue
        # skip if already a circle hit
        if any(abs(ax - px) < 18 and abs(ay - py) < 18 for px, py, _, _ in pts):
            continue
        diamonds.append((ax, ay))
        if len(diamonds) >= 12:
            break
        cv2.drawMarker(vis, (ax, ay), (0, 0, 255), cv2.MARKER_DIAMOND, 18, 2)

    print("circles:")
    for ax, ay, r, t in sorted(pts, key=lambda p: (p[1], p[0])):
        print(f"  shot=({ax},{ay}) 1440=({int(ax*scale)},{int(ay*scale)}) r={r}")
    print("diamonds:")
    for ax, ay in sorted(diamonds, key=lambda p: (p[1], p[0])):
        print(f"  shot=({ax},{ay}) 1440=({int(ax*scale)},{int(ay*scale)})")

    # Overlay current config clicks (magenta=skill, orange=nodes)
    cur_skills = [(1007, 1207), (1313, 1020), (1680, 940), (2047, 1020), (2347, 1207)]
    offset = 340
    for i, (X, Y) in enumerate(cur_skills):
        sx, sy = int(X / scale), int(Y / scale)
        cv2.circle(vis, (sx, sy), 12, (255, 0, 255), 2)
        cv2.putText(vis, f"S{i}", (sx - 8, sy - 14), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 0, 255), 1)
        for n in (1, 2):
            ny = int((Y - offset * n) / scale)
            cv2.circle(vis, (sx, ny), 7, (0, 165, 255), 2)

    # Manual estimate marks from visual layout (shot coords) — refine by eye
    # Bottom 5 skills roughly evenly spaced across tree
    # From the screenshot: skills sit above Outro/Tune Break row
    guess_skills_shot = [
        (280, 430),  # normal
        (400, 400),  # resonance
        (512, 385),  # forte center
        (624, 400),  # liberation
        (744, 430),  # intro
    ]
    for i, (sx, sy) in enumerate(guess_skills_shot):
        cv2.circle(vis, (sx, sy), 9, (255, 255, 0), 2)
        cv2.putText(vis, f"G{i}", (sx - 8, sy + 22), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 0), 1)
        print(f"guess S{i} shot=({sx},{sy}) 1440=({int(sx*scale)},{int(sy*scale)})")

    cv2.imwrite(str(OUT / "overlay.png"), vis)
    print("wrote", OUT / "overlay.png")


if __name__ == "__main__":
    main()
