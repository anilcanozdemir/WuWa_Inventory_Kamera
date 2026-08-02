"""Always-on-top character Echo ROI recorder (Start button).

Open Resonators → Echo overview (5 slots on the RIGHT arc), then:
  tools\\START_RECORD_ECHO.bat

For STAT columns only (slots already calibrated):
  tools\\START_RECORD_ECHO_STATS.bat

Click order (full recorder):
  1) ENTER — overview top slot
  2-6) LEFT slots 1→5
  7-8) NAME TL/BR
  9-10) LEVEL TL/BR
  11-12) STAT NAMES TL/BR (first ATK → last sub; no COST / no Echo Skill)
  13-14) STAT VALUES TL/BR

No Esc between slots. Save & exit when done.
"""
from __future__ import annotations

import json
import sys
import threading
time_mod = __import__("time")
import tkinter as tk
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LBUTTON_VK = 0x01
ABORT_VK = 0x7B

STEPS: list[tuple[str, str]] = [
    ("echoEnterClick", "ENTER (overview top slot)"),
    ("slot0", "LEFT slot 1 (top)"),
    ("slot1", "LEFT slot 2"),
    ("slot2", "LEFT slot 3"),
    ("slot3", "LEFT slot 4"),
    ("slot4", "LEFT slot 5 (bottom)"),
    ("echoDetailName", "NAME top-left"),
    ("echoDetailName", "NAME bottom-right"),
    ("echoDetailLevel", "LEVEL (+N) top-left"),
    ("echoDetailLevel", "LEVEL bottom-right"),
    ("echoFullStatsName", "STAT NAMES col top-left (ATK..)"),
    ("echoFullStatsName", "STAT NAMES col bottom-right"),
    ("echoFullStatsValue", "STAT VALUES col top-left"),
    ("echoFullStatsValue", "STAT VALUES col bottom-right"),
]


class EchoRoiRecorder:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Echo ROI recorder")
        self.root.attributes("-topmost", True)
        self.root.geometry("440x230+40+40")
        self.root.resizable(False, False)

        self.status = tk.StringVar(
            value="Echo overview open? Start → enter equip UI → left slots → box right panel."
        )
        self.step = tk.StringVar(value="Idle")
        self.last = tk.StringVar(value="")

        tk.Label(self.root, textvariable=self.status, wraplength=420, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        tk.Label(self.root, textvariable=self.step, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=10, pady=4
        )
        tk.Label(self.root, textvariable=self.last, fg="#444", wraplength=420).pack(
            anchor="w", padx=10, pady=2
        )

        row = tk.Frame(self.root)
        row.pack(fill="x", padx=10, pady=10)
        self.btn_start = tk.Button(row, text="Start", width=12, command=self.start)
        self.btn_start.pack(side="left", padx=2)
        self.btn_save = tk.Button(
            row, text="Save & exit", width=12, state="disabled", command=self.finish
        )
        self.btn_save.pack(side="left", padx=2)

        self._ox = self._oy = 0
        self._res = (2560, 1440)
        self._points: dict[str, list[list[int]]] = {
            "echoEnterClick": [],
            "slot0": [],
            "slot1": [],
            "slot2": [],
            "slot3": [],
            "slot4": [],
            "echoDetailName": [],
            "echoDetailLevel": [],
            "echoFullStatsName": [],
            "echoFullStatsValue": [],
        }
        self._stop = False
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def start(self) -> None:
        try:
            from game.foreground import WindowManager
            import mss

            wm = WindowManager()
            if wm.setForeground()[0] == "error":
                self.status.set("Game window not found")
                return
            time_mod.sleep(0.3)
            screen = wm.getScreenInfo()
            self._res = (int(screen.width), int(screen.height))
            with mss.mss() as sct:
                mon = sct.monitors[screen.monitor]
            self._ox, self._oy = int(mon["left"]), int(mon["top"])
        except Exception as e:
            self.status.set(f"Init failed: {e}")
            return

        self._points = {k: [] for k in self._points}
        self._stop = False
        self.btn_start.config(state="disabled")
        self.btn_save.config(state="normal")
        self.status.set(
            "Stay on equip UI. Box NAME, LEVEL, then STAT NAMES column and STAT VALUES column "
            "(ATK.. through last sub — stop before Echo Skill)."
        )
        threading.Thread(target=self._run, daemon=True).start()

    def finish(self) -> None:
        self._stop = True
        self._save()
        self.root.after(200, self.root.destroy)

    def _on_close(self) -> None:
        self._stop = True
        if any(self._points.values()):
            self._save()
        self.root.destroy()

    def _wait_click(self) -> tuple[int, int] | None:
        import win32api
        import win32gui

        while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
            time_mod.sleep(0.02)
        our = int(self.root.winfo_id())
        while not self._stop:
            if win32api.GetAsyncKeyState(ABORT_VK) & 0x8000:
                self._stop = True
                return None
            if win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                x, y = win32gui.GetCursorPos()
                hwnd = win32gui.WindowFromPoint((x, y))
                on_ui = False
                cur = hwnd
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
                    time_mod.sleep(0.02)
                if on_ui:
                    continue
                return int(x - self._ox), int(y - self._oy)
            time_mod.sleep(0.02)
        return None

    def _run(self) -> None:
        for key, label in STEPS:
            if self._stop:
                break
            self.root.after(0, lambda l=label: self.step.set(f"Click {l}"))
            pt = self._wait_click()
            if pt is None:
                break
            self._points[key].append([pt[0], pt[1]])
            self.root.after(
                0,
                lambda k=key, p=pt: self.last.set(f"{k} += ({p[0]},{p[1]})"),
            )
        self.root.after(0, lambda: self.step.set("Done — Save & exit"))
        self.root.after(0, lambda: self.status.set("All points captured."))

    def _box(self, pts: list[list[int]]) -> list[int] | None:
        if len(pts) < 2:
            return None
        (x0, y0), (x1, y1) = pts[0], pts[1]
        x, y = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        return [x, y, max(w, 1), max(h, 1)]

    def _save(self) -> None:
        out = ROOT / "debug_out" / f"echo_rois_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        enter_pts = self._points.get("echoEnterClick") or []
        slots = []
        for i in range(5):
            pts = self._points.get(f"slot{i}") or []
            if pts:
                slots.append(pts[0])
        boxes = {
            "echoDetailName": self._box(self._points.get("echoDetailName") or []),
            "echoDetailLevel": self._box(self._points.get("echoDetailLevel") or []),
            "echoFullStatsName": self._box(self._points.get("echoFullStatsName") or []),
            "echoFullStatsValue": self._box(self._points.get("echoFullStatsValue") or []),
        }
        report = {
            "out": str(out),
            "resolution": list(self._res),
            "points": self._points,
            "echoEnterClick": enter_pts[0] if enter_pts else None,
            "echoSlotPositions": slots,
            "boxes": boxes,
            "gameROI": {
                "echoEnterClick": (
                    f"Coordinates({enter_pts[0][0]}, {enter_pts[0][1]})" if enter_pts else None
                ),
                "echoSlotPositions": [f"Coordinates({p[0]}, {p[1]})" for p in slots],
                **{
                    k: (f"Coordinates({b[0]}, {b[1]}, {b[2]}, {b[3]})" if b else None)
                    for k, b in boxes.items()
                },
            },
        }
        (out / "rois.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (ROOT / "debug_out" / "_latest_echo_rois.txt").write_text(str(out), encoding="utf-8")
        self.status.set(f"Saved {out / 'rois.json'}")

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    EchoRoiRecorder().run()
