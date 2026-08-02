"""Always-on-top Resonance Chain click recorder.

Run: tools\\START_RECORD_CHAIN.bat

1. Open Resonators → pick Aalto (or anyone) → open Chain tab
2. Press Start on the floating window
3. Click S1 … S6 in order (the constellation nodes on the right)
4. Optionally click the "Activated" / status label on the left panel (for ROI)
5. Save & exit → writes clicks.json and updates gameROI.py 1440p chainPositions

F12 aborts.
"""
from __future__ import annotations

import json
import re
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

ABORT_VK = 0x7B
LBUTTON_VK = 0x01


class ChainClickRecorder:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Chain click recorder")
        self.root.attributes("-topmost", True)
        self.root.geometry("400x240+40+40")
        self.root.resizable(False, False)

        self.status = tk.StringVar(
            value="Open Chain tab in game, then press Start. Click S1→S6."
        )
        self.step = tk.StringVar(value="Idle")
        self.last = tk.StringVar(value="")

        tk.Label(self.root, textvariable=self.status, wraplength=380, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        tk.Label(self.root, textvariable=self.step, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=10, pady=4
        )
        tk.Label(self.root, textvariable=self.last, fg="#444", wraplength=380).pack(
            anchor="w", padx=10, pady=2
        )

        row = tk.Frame(self.root)
        row.pack(fill="x", padx=10, pady=10)
        self.btn_start = tk.Button(row, text="Start", width=10, command=self.start)
        self.btn_start.pack(side="left", padx=2)
        self.btn_skip = tk.Button(
            row, text="Skip node", width=10, state="disabled", command=self.skip
        )
        self.btn_skip.pack(side="left", padx=2)
        self.btn_done = tk.Button(
            row, text="Save & exit", width=10, state="disabled", command=self.finish
        )
        self.btn_done.pack(side="left", padx=2)

        self._recording = False
        self._skip = False
        self._stop = False
        self._ox = 0
        self._oy = 0
        self._res = (2560, 1440)
        self.nodes: list[list[int] | None] = []
        self.activated_roi: list[int] | None = None  # x,y of a sample Activated click
        self._thread: threading.Thread | None = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def start(self) -> None:
        if self._recording:
            return
        try:
            from game.foreground import WindowManager
            import mss

            wm = WindowManager()
            if wm.setForeground()[0] == "error":
                self.status.set("Game window not found.")
                return
            time.sleep(0.3)
            screen = wm.getScreenInfo()
            self._res = (int(screen.width), int(screen.height))
            with mss.mss() as sct:
                mon = sct.monitors[screen.monitor]
            self._ox, self._oy = int(mon["left"]), int(mon["top"])
        except Exception as e:
            self.status.set(f"Init failed: {e}")
            return

        self.nodes = []
        self.activated_roi = None
        self._recording = True
        self._stop = False
        self.btn_start.config(state="disabled")
        self.btn_skip.config(state="normal")
        self.btn_done.config(state="normal")
        self.status.set(
            f"Recording {self._res[0]}x{self._res[1]}. Click constellation nodes in game."
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def skip(self) -> None:
        self._skip = True

    def finish(self) -> None:
        self._stop = True
        self._save()
        self.root.after(200, self.root.destroy)

    def _on_close(self) -> None:
        self._stop = True
        if self.nodes:
            self._save()
        self.root.destroy()

    def _wait_click(self) -> tuple[int, int] | None:
        import win32api
        import win32gui

        while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
            time.sleep(0.02)

        while not self._stop:
            if win32api.GetAsyncKeyState(ABORT_VK) & 0x8000:
                self._stop = True
                return None
            if self._skip:
                self._skip = False
                return None
            if win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                x, y = win32gui.GetCursorPos()
                hwnd = win32gui.WindowFromPoint((x, y))
                our = int(self.root.winfo_id())
                cur = hwnd
                on_ui = False
                for _ in range(8):
                    if not cur:
                        break
                    if cur == our:
                        on_ui = True
                        break
                    try:
                        cur = win32gui.GetParent(cur)
                    except Exception:
                        break
                while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                    time.sleep(0.02)
                if on_ui:
                    continue
                return int(x - self._ox), int(y - self._oy)
            time.sleep(0.02)
        return None

    def _run(self) -> None:
        try:
            for i in range(1, 7):
                if self._stop:
                    break
                self.root.after(0, lambda n=i: self.step.set(f"Click chain node S{n}"))
                pt = self._wait_click()
                if self._stop:
                    break
                if pt is None:
                    self.nodes.append(None)
                    self.root.after(0, lambda n=i: self.last.set(f"Skipped S{n}"))
                    continue
                self.nodes.append([pt[0], pt[1]])
                self.root.after(
                    0,
                    lambda n=i, x=pt[0], y=pt[1]: self.last.set(f"S{n}=({x},{y})"),
                )

            if not self._stop:
                self.root.after(
                    0,
                    lambda: self.step.set(
                        "Optional: click Activated label (left panel), or Save & exit"
                    ),
                )
                pt = self._wait_click()
                if pt is not None:
                    self.activated_roi = [pt[0], pt[1]]
                    self.root.after(
                        0,
                        lambda x=pt[0], y=pt[1]: self.last.set(f"Activated≈({x},{y})"),
                    )

            self.root.after(0, lambda: self.step.set("Done — press Save & exit"))
            self.root.after(0, lambda: self.status.set("Nodes captured."))
        except Exception as e:
            self.root.after(0, lambda: self.status.set(f"Error: {e}"))

    def _save(self) -> None:
        out = ROOT / "debug_out" / f"chain_clicks_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        positions = [n for n in self.nodes if n]
        report = {
            "out": str(out),
            "monitor_origin": [self._ox, self._oy],
            "resolution": list(self._res),
            "chainPositions": self.nodes,
            "chainPositions_filled": positions,
            "activated_sample": self.activated_roi,
            # First node also used as chainClick (upstream opens S1 graphic first).
            "chainClick": positions[0] if positions else None,
        }
        (out / "clicks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (ROOT / "debug_out" / "_latest_chain_clicks.txt").write_text(str(out), encoding="utf-8")

        patched = False
        if len(positions) >= 1 and self._res == (2560, 1440):
            patched = self._patch_game_roi(positions, self.activated_roi)
        self.status.set(
            f"Saved {out / 'clicks.json'}"
            + (" + gameROI patched" if patched else " (ROI not patched — check res/count)")
        )

    def _patch_game_roi(
        self, positions: list[list[int]], activated: list[int] | None
    ) -> bool:
        """Patch only the 2560x1440 characters block (anchor: weaponName 270,264)."""
        path = ROOT / "game" / "gameROI.py"
        text = path.read_text(encoding="utf-8")
        # Slice from 1440p weaponName through end of that characters dict's chainPositions.
        m = re.search(
            r'"weaponName": Coordinates\(270, 264[\s\S]*?"chainPositions": \[([\s\S]*?)\],',
            text,
        )
        if not m:
            return False
        pos_block = ",\n".join(
            f"                    Coordinates({x}, {y})" for x, y in positions
        )
        text2 = (
            text[: m.start(1)]
            + "\n"
            + pos_block
            + "\n                "
            + text[m.end(1) :]
        )
        x0, y0 = positions[0]
        text2, n = re.subn(
            r'("weaponName": Coordinates\(270, 264[\s\S]*?)"chainClick": Coordinates\(\d+, \d+\)',
            rf'\1"chainClick": Coordinates({x0}, {y0})',
            text2,
            count=1,
        )
        if n != 1:
            return False
        if activated and len(activated) == 2:
            ax, ay = activated
            text2, _ = re.subn(
                r'("weaponName": Coordinates\(270, 264[\s\S]*?)"chainButton": Coordinates\(\d+, \d+, \d+, \d+\)',
                rf'\1"chainButton": Coordinates({max(0, ax - 80)}, {max(0, ay - 20)}, 160, 48)',
                text2,
                count=1,
            )
        path.write_text(text2, encoding="utf-8")
        return True

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    ChainClickRecorder().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
