"""Emit a (2560, 1440) COORDINATES block derived from 1080p + video calibration."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.gameROI import COORDINATES, Coordinates


def scale_coord(c: Coordinates, sx: float, sy: float) -> Coordinates:
    return Coordinates(
        x=c.x * sx if c.x else 0,
        y=c.y * sy if c.y else 0,
        w=c.w * sx if c.w else 0,
        h=c.h * sy if c.h else 0,
    )


def scale_obj(obj, sx: float, sy: float):
    if isinstance(obj, Coordinates):
        return scale_coord(obj, sx, sy)
    if isinstance(obj, dict):
        return {k: scale_obj(v, sx, sy) for k, v in obj.items()}
    if isinstance(obj, list):
        return [scale_obj(v, sx, sy) for v in obj]
    return obj


def fmt(c: Coordinates) -> str:
    def n(v):
        if not v:
            return 0
        return int(v) if float(v) == int(v) else round(float(v), 2)

    x, y, w, h = n(c.x), n(c.y), n(c.w), n(c.h)
    if x == 0 and w == 0 and h == 0:
        return f"Coordinates(y={y})"
    if w == 0 and h == 0:
        return f"Coordinates({x}, {y})"
    return f"Coordinates({x}, {y}, {w}, {h})"


def emit(obj, indent: int = 0) -> str:
    pad = "    " * indent
    if isinstance(obj, Coordinates):
        return fmt(obj)
    if isinstance(obj, list):
        lines = [pad + "["]
        for item in obj:
            lines.append(pad + "    " + emit(item, 0) + ",")
        lines.append(pad + "]")
        return "\n".join(lines)
    if isinstance(obj, dict):
        lines = []
        for key, value in obj.items():
            if isinstance(value, dict):
                lines.append(f'{pad}"{key}": {{')
                inner = emit(value, indent + 1)
                lines.append(inner)
                lines.append(pad + "},")
            elif isinstance(value, list):
                lines.append(f'{pad}"{key}": [')
                for item in value:
                    lines.append(pad + "    " + emit(item, 0) + ",")
                lines.append(pad + "],")
            else:
                lines.append(f'{pad}"{key}": {emit(value, 0)},')
        return "\n".join(lines)
    return repr(obj)


def main() -> int:
    src = COORDINATES[(16, 9)][(1920, 1080)]
    dst = scale_obj(src, 2560 / 1920, 1440 / 1080)

    # Calibrated from 2026-08-01 screen recording (720p capture of 1440p client).
    dst["characters"]["resonatorName"] = Coordinates(260, 248, 520, 56)
    dst["characters"]["resonatorLevel"] = Coordinates(260, 318, 420, 56)
    dst["characters"]["leftSide"] = Coordinates(108, 254)
    dst["characters"]["rightSide"] = Coordinates(2418, 270)
    dst["characters"]["offsets"]["leftSide"] = Coordinates(y=100)
    dst["characters"]["offsets"]["rightSide"] = Coordinates(y=140)

    print("(2560, 1440): {")
    print(emit(dst, 1))
    print("},")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
