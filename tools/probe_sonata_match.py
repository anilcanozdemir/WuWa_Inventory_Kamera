"""Measure how sonata icon matching behaves under small misalignment.

The live scan logged best scores of 0.71-0.81 for badges whose templates were
already on disk. This probe checks whether that is explained by the current
same-size matchTemplate call (which yields a 1x1 result and so cannot tolerate
any shift), and whether searching a smaller template inside a larger haystack
restores intra-class scores without collapsing the gap to other badges.
"""

from __future__ import annotations

import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ICON_DIR = ROOT / 'assets' / 'sonata'
CANON = 44
INNER = 32  # template side for the padded-search variant


def load() -> list[tuple[str, np.ndarray]]:
    out = []
    for path in sorted(ICON_DIR.glob('*.png')):
        if path.name.startswith('_'):
            continue
        img = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if img is None or img.size == 0:
            continue
        out.append((path.stem, cv2.resize(img, (CANON, CANON), interpolation=cv2.INTER_AREA)))
    return out


def shift(img: np.ndarray, dx: int, dy: int) -> np.ndarray:
    m = np.float32([[1, 0, dx], [0, 1, dy]])
    return cv2.warpAffine(img, m, (img.shape[1], img.shape[0]), borderMode=cv2.BORDER_REPLICATE)


def inner(img: np.ndarray) -> np.ndarray:
    off = (CANON - INNER) // 2
    return img[off:off + INNER, off:off + INNER]


def score_same(hay: np.ndarray, tmpl: np.ndarray) -> float:
    r = cv2.matchTemplate(hay, tmpl, cv2.TM_CCOEFF_NORMED)
    return float(r.max()) if r.size else 0.0


def score_search(hay: np.ndarray, tmpl: np.ndarray) -> float:
    r = cv2.matchTemplate(hay, inner(tmpl), cv2.TM_CCOEFF_NORMED)
    return float(r.max()) if r.size else 0.0


def degrade(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Approximate a live crop: resampling softness, sensor-ish noise, scale drift."""
    scale = rng.uniform(0.94, 1.06)
    side = max(8, int(round(img.shape[0] * scale)))
    out = cv2.resize(img, (side, side), interpolation=cv2.INTER_LINEAR)
    out = cv2.resize(out, (img.shape[1], img.shape[0]), interpolation=cv2.INTER_LINEAR)
    out = cv2.GaussianBlur(out, (3, 3), 0.6)
    noise = rng.normal(0, 6, out.shape)
    return np.clip(out.astype(np.float32) + noise, 0, 255).astype(np.uint8)


def main() -> int:
    tpl = load()
    print(f'{len(tpl)} templates from {ICON_DIR}')
    shifts = [(0, 0), (1, 0), (0, 1), (2, 1), (-2, 1), (2, 2), (-3, 2), (3, -3)]

    for label, fn in (('CURRENT same-size', score_same), ('PROPOSED padded search', score_search)):
        intra: list[float] = []
        intra_worst: dict[str, float] = {}
        inter: list[float] = []
        confusions = 0
        margins: list[float] = []

        for name, img in tpl:
            for dx, dy in shifts:
                hay = shift(img, dx, dy)
                scores = sorted(((fn(hay, t), n) for n, t in tpl), reverse=True)
                best_score, best_name = scores[0]
                own = next(s for s, n in scores if n == name)
                intra.append(own)
                intra_worst[name] = min(intra_worst.get(name, 1.0), own)
                others = [s for s, n in scores if n != name]
                inter.append(max(others))
                runner_up = max(others)
                margins.append(own - runner_up)
                if best_name != name:
                    confusions += 1

        print(f'\n=== {label} ===')
        print(f'  intra-class (correct badge): min {min(intra):.3f}  mean {np.mean(intra):.3f}')
        print(f'  inter-class (best wrong)   : max {max(inter):.3f}  mean {np.mean(inter):.3f}')
        print(f'  own-minus-runner-up margin : min {min(margins):+.3f}  mean {np.mean(margins):+.3f}')
        print(f'  wrong-badge-wins           : {confusions}/{len(tpl) * len(shifts)}')
        worst = sorted(intra_worst.items(), key=lambda kv: kv[1])[:5]
        print('  weakest badges under shift : ' + ', '.join(f'{n} {v:.3f}' for n, v in worst))

    # Threshold choice must survive a realistic crop, not just a clean shift.
    rng = np.random.default_rng(7)
    own_scores: list[float] = []
    runner_scores: list[float] = []
    margins: list[float] = []
    confusions = 0
    unknown_best: list[float] = []
    unknown_margin: list[float] = []

    for name, img in tpl:
        for dx, dy in shifts:
            hay = degrade(shift(img, dx, dy), rng)
            scores = sorted(((score_search(hay, t), n) for n, t in tpl), reverse=True)
            own = next(s for s, n in scores if n == name)
            runner = max(s for s, n in scores if n != name)
            own_scores.append(own)
            runner_scores.append(runner)
            margins.append(own - runner)
            if scores[0][1] != name:
                confusions += 1

        # Simulate a badge that is NOT in the library: match it while its own
        # template is held out, so we can see what an unknown icon looks like.
        held = [(n, t) for n, t in tpl if n != name]
        hay = degrade(shift(img, 1, -1), rng)
        s = sorted(((score_search(hay, t), n) for n, t in held), reverse=True)
        unknown_best.append(s[0][0])
        unknown_margin.append(s[0][0] - s[1][0])

    print('\n=== PROPOSED on degraded (noisy/blurred/rescaled) crops ===')
    print(f'  known badge, own score     : min {min(own_scores):.3f}  mean {np.mean(own_scores):.3f}')
    print(f'  known badge, runner-up     : max {max(runner_scores):.3f}  mean {np.mean(runner_scores):.3f}')
    print(f'  known badge, margin        : min {min(margins):+.3f}  mean {np.mean(margins):+.3f}')
    print(f'  wrong-badge-wins           : {confusions}/{len(tpl) * len(shifts)}')
    print(f'  UNKNOWN badge, best score  : max {max(unknown_best):.3f}  mean {np.mean(unknown_best):.3f}')
    print(f'  UNKNOWN badge, margin      : max {max(unknown_margin):+.3f}  mean {np.mean(unknown_margin):+.3f}')

    print('\n=== threshold sweep (accept if score >= MIN and margin >= MARGIN) ===')
    print('   MIN MARGIN   known-accepted  known-wrong  unknown-wrongly-accepted')
    for mn in (0.70, 0.75, 0.80, 0.85):
        for mg in (0.00, 0.03, 0.05, 0.08):
            ok = sum(1 for o, r in zip(own_scores, runner_scores) if o >= mn and o - r >= mg)
            bad = sum(1 for o, r in zip(own_scores, runner_scores) if r >= mn and r - o >= mg)
            unk = sum(1 for b, m in zip(unknown_best, unknown_margin) if b >= mn and m >= mg)
            print(f'  {mn:.2f}  {mg:.2f}   {ok:4d}/{len(own_scores)}        {bad:4d}         {unk:3d}/{len(unknown_best)}')

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
