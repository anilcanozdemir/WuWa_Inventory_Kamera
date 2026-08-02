"""Record Aalto portrait click (always-on-top).

Scroll the Resonator roster until Taoqi / Aalto / Chixia are visible, then:
  tools\\START_RECORD_AALTO.bat

Click Aalto's portrait CENTER once. Optionally click again after a tiny nudge
if the first click looked off. Save writes data/aalto_click.json.
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


class AaltoClickRecorder:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Aalto click recorder")
        self.root.attributes("-topmost", True)
        self.root.geometry("420x200+40+40")
        self.root.resizable(False, False)

        self.status = tk.StringVar(
            value="Show Taoqi / Aalto / Chixia on the roster, then Start → click Aalto."
        )
        self.step = tk.StringVar(value="Idle")
        self.last = tk.StringVar(value="")

        tk.Label(self.root, textvariable=self.status, wraplength=400, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        tk.Label(self.root, textvariable=self.step, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=10, pady=4
        )
        tk.Label(self.root, textvariable=self.last, fg="#444", wraplength=400).pack(
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
        self._clicks: list[list[int]] = []
        self._stop = False
        self._our_hwnds: set[int] = set()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _refresh_hwnds(self) -> None:
        import win32gui

        hwnds: set[int] = set()
        root_hwnd = int(self.root.winfo_id())
        hwnds.add(root_hwnd)

        def enum_child(hwnd, _):
            hwnds.add(int(hwnd))
            return True

        try:
            win32gui.EnumChildWindows(root_hwnd, enum_child, None)
        except Exception:
            pass
        self._our_hwnds = hwnds

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

        self.root.update_idletasks()
        self._refresh_hwnds()
        self._clicks = []
        self._stop = False
        self.btn_start.config(state="disabled")
        self.btn_save.config(state="normal")
        self.status.set("Click Aalto portrait center (can click 2–3 times if unsure).")
        self.step.set("Click Aalto")
        threading.Thread(target=self._run, daemon=True).start()

    def finish(self) -> None:
        self._stop = True
        self._save()
        self.root.after(200, self.root.destroy)

    def _on_close(self) -> None:
        self._stop = True
        if self._clicks:
            self._save()
        self.root.destroy()

    def _on_our_ui(self, hwnd: int) -> bool:
        cur = int(hwnd)
        for _ in range(10):
            if cur in self._our_hwnds:
                return True
            try:
                import win32gui

                parent = win32gui.GetParent(cur)
            except Exception:
                break
            if not parent or parent == cur:
                break
            cur = int(parent)
        return False

    def _run(self) -> None:
        import win32api
        import win32gui

        while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
            time_mod.sleep(0.02)
        while not self._stop:
            if win32api.GetAsyncKeyState(ABORT_VK) & 0x8000:
                break
            if win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                x, y = win32gui.GetCursorPos()
                hwnd = win32gui.WindowFromPoint((x, y))
                on_ui = self._on_our_ui(hwnd)
                while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                    time_mod.sleep(0.02)
                if on_ui:
                    continue
                pt = [int(x - self._ox), int(y - self._oy)]
                self._clicks.append(pt)
                self.root.after(
                    0,
                    lambda p=pt, n=len(self._clicks): self.last.set(
                        f"click{n} = ({p[0]},{p[1]})"
                    ),
                )
                if len(self._clicks) >= 1:
                    self.root.after(
                        0,
                        lambda: self.status.set(
                            "Got it. Click again to refine, or Save & exit."
                        ),
                    )
            time_mod.sleep(0.02)
        self._save()
        self.root.after(200, self.root.destroy)

    def _save(self) -> None:
        if not self._clicks:
            return
        out = ROOT / "debug_out" / f"aalto_click_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        xs = [c[0] for c in self._clicks]
        ys = [c[1] for c in self._clicks]
        x = int(round(sum(xs) / len(xs)))
        y = int(round(sum(ys) / len(ys)))
        report = {
            "out": str(out),
            "resolution": list(self._res),
            "clicks": self._clicks,
            "aaltoClick": [x, y],
            "gameROI": f"Coordinates({x}, {y})",
        }
        (out / "click.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (ROOT / "debug_out" / "_latest_aalto_click.txt").write_text(str(out), encoding="utf-8")
        (ROOT / "data" / "aalto_click.json").write_text(
            json.dumps({"x": x, "y": y, "clicks": self._clicks}, indent=2),
            encoding="utf-8",
        )
        try:
            self.status.set(f"Saved Aalto @ ({x},{y})")
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    AaltoClickRecorder().run()
