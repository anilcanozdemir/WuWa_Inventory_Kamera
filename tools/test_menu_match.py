"""Unit checks for main-menu text matching (no game / OCR required)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from game.menu import (
    looksLikeTerminalFeatureNoise,
    normalizeMenuText,
    textLooksLikeTerminal,
)


def expect(cond: bool, msg: str) -> None:
    if not cond:
        raise AssertionError(msg)


def main() -> int:
    expect(normalizeMenuText("Terminal") == "terminal", "basic normalize")
    expect(normalizeMenuText("Ter mi-nal\n") == "terminal", "spaces/dashes/newlines")

    expect(textLooksLikeTerminal("Terminal", "terminal"), "exact")
    expect(textLooksLikeTerminal("TERMINAL", "terminal"), "case")
    expect(textLooksLikeTerminal("Terminal\nGuide", "terminal"), "extra line")
    expect(textLooksLikeTerminal("Termina1", "terminal"), "ocr noise")
    expect(textLooksLikeTerminal("erminal", "terminal"), "missing T")
    expect(not textLooksLikeTerminal("", "terminal"), "empty")
    expect(not textLooksLikeTerminal("thumaczgoogleyoutube", "terminal"), "wrong monitor")
    expect(not textLooksLikeTerminal("github.co", "terminal"), "browser leak")

    expect(looksLikeTerminalFeatureNoise("pioneerconvenepodcast"), "podcast junk")
    expect(looksLikeTerminalFeatureNoise("Data Bank"), "databank junk")
    expect(not looksLikeTerminalFeatureNoise("blazingclaw"), "real item")

    print("ok: menu text matching")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
