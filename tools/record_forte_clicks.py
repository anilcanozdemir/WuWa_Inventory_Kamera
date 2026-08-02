"""Always-on-top Forte click recorder with a Start button.

Run: tools\\START_RECORD_CLICKS.bat

1. Open Forte overview in game
2. Press Start on the floating window
3. Click skills/nodes in game — the window shows what to click next
4. Use Skip Node / Skip Skill if needed; Done saves JSON
"""
from __future__ import annotations

import json
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

LABELS = ["normal", "resonance", "forte", "liberation", "intro"]


class ForteClickRecorder:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Forte click recorder")
        self.root.attributes("-topmost", True)
        self.root.geometry("360x220+40+40")
        self.root.resizable(False, False)

        self.status = tk.StringVar(value="Open Forte overview, then press Start.")
        self.step = tk.StringVar(value="Idle")
        self.last = tk.StringVar(value="")

        tk.Label(self.root, textvariable=self.status, wraplength=340, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        tk.Label(self.root, textvariable=self.step, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=10, pady=4
        )
        tk.Label(self.root, textvariable=self.last, fg="#444", wraplength=340).pack(
            anchor="w", padx=10, pady=2
        )

        row = tk.Frame(self.root)
        row.pack(fill="x", padx=10, pady=10)
        self.btn_start = tk.Button(row, text="Start", width=10, command=self.start)
        self.btn_start.pack(side="left", padx=2)
        self.btn_skip_node = tk.Button(
            row, text="Skip node", width=10, state="disabled", command=self.skip_node
        )
        self.btn_skip_node.pack(side="left", padx=2)
        self.btn_skip_skill = tk.Button(
            row, text="Skip skill", width=10, state="disabled", command=self.skip_skill
        )
        self.btn_skip_skill.pack(side="left", padx=2)
        self.btn_done = tk.Button(
            row, text="Save & exit", width=10, state="disabled", command=self.finish
        )
        self.btn_done.pack(side="left", padx=2)

        self._recording = False
        self._armed = False  # ignore clicks until Start
        self._skip_node = False
        self._skip_skill = False
        self._stop = False
        self._ox = 0
        self._oy = 0
        self._res = (2560, 1440)
        self.skills: list[dict] = []
        self._thread: threading.Thread | None = None

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_recording_ui(self, on: bool) -> None:
        self.btn_start.config(state="disabled" if on else "normal")
        st = "normal" if on else "disabled"
        self.btn_skip_node.config(state=st)
        self.btn_skip_skill.config(state=st)
        self.btn_done.config(state=st)

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

        self.skills = []
        self._recording = True
        self._armed = True
        self._stop = False
        self._set_recording_ui(True)
        self.status.set(
            f"Recording {self._res[0]}x{self._res[1]}. Click in game; keep this window visible."
        )
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def skip_node(self) -> None:
        self._skip_node = True

    def skip_skill(self) -> None:
        self._skip_skill = True

    def finish(self) -> None:
        self._stop = True
        self._save()
        self.root.after(200, self.root.destroy)

    def _on_close(self) -> None:
        self._stop = True
        if self.skills:
            self._save()
        self.root.destroy()

    def _wait_click(self) -> tuple[int, int] | None:
        """Left-click → client (x,y). Skip node/skill/stop → None with flags."""
        import win32api

        while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
            time.sleep(0.02)

        while not self._stop:
            if win32api.GetAsyncKeyState(ABORT_VK) & 0x8000:
                self._stop = True
                return None
            if self._skip_node or self._skip_skill:
                return None
            # Ignore clicks on our recorder window
            if win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                import win32gui

                x, y = win32gui.GetCursorPos()
                hwnd = win32gui.WindowFromPoint((x, y))
                our = int(self.root.winfo_id())
                # Walk parents — if click is on tk window, ignore
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
            for name in LABELS:
                if self._stop:
                    break
                self._skip_skill = False
                self.root.after(
                    0,
                    lambda n=name: self.step.set(f"Click skill: {n.upper()}"),
                )
                pt = self._wait_click()
                if self._stop:
                    break
                if self._skip_skill or pt is None:
                    self._skip_skill = False
                    self.skills.append({"name": name, "skill": None, "nodes": []})
                    self.root.after(0, lambda n=name: self.last.set(f"Skipped skill {n}"))
                    continue

                sx, sy = pt
                self.root.after(
                    0,
                    lambda n=name, x=sx, y=sy: self.last.set(f"{n} skill=({x},{y})"),
                )
                nodes: list[list[int]] = []
                for n in (1, 2):
                    if self._stop:
                        break
                    self._skip_node = False
                    self.root.after(
                        0,
                        lambda n=name, i=n: self.step.set(f"{n.upper()}: click NODE {i} (or Skip node)"),
                    )
                    npt = self._wait_click()
                    if self._stop:
                        break
                    if self._skip_skill:
                        break
                    if self._skip_node or npt is None:
                        self._skip_node = False
                        break
                    nodes.append([npt[0], npt[1]])
                    self.root.after(
                        0,
                        lambda i=n, x=npt[0], y=npt[1]: self.last.set(f"node{i}=({x},{y})"),
                    )
                    time.sleep(0.1)

                self.skills.append({"name": name, "skill": [sx, sy], "nodes": nodes})
                self._skip_skill = False

            self.root.after(0, lambda: self.step.set("Done — press Save & exit"))
            self.root.after(0, lambda: self.status.set("All skills captured (or stopped)."))
            self.root.after(0, lambda: self.btn_start.config(state="disabled"))
        except Exception as e:
            self.root.after(0, lambda: self.status.set(f"Error: {e}"))

    def _save(self) -> None:
        out = ROOT / "debug_out" / f"forte_clicks_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        positions = []
        offsets = []
        abs_nodes = []
        for s in self.skills:
            if not s.get("skill"):
                positions.append(None)
                offsets.append([])
                abs_nodes.append([])
                continue
            sx, sy = s["skill"]
            positions.append([sx, sy])
            abs_nodes.append(s["nodes"])
            offsets.append([sy - ny for nx, ny in s["nodes"]])

        report = {
            "out": str(out),
            "monitor_origin": [self._ox, self._oy],
            "resolution": list(self._res),
            "skills": self.skills,
            "skillPositions": positions,
            "skillNodeOffsets": offsets,
            "skillNodes": abs_nodes,
        }
        (out / "clicks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (ROOT / "debug_out" / "_latest_forte_clicks.txt").write_text(str(out), encoding="utf-8")
        self.status.set(f"Saved {out / 'clicks.json'}")

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    ForteClickRecorder().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
