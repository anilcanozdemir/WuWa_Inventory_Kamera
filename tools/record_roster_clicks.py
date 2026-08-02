"""Always-on-top resonator roster click recorder.

Open Resonators → Overview at TOP of the list, then:
  tools\\START_RECORD_ROSTER.bat

1) PAGE 1 — click 6 portrait centers (top→bottom), then Page done
2) SCROLL — drag ONE PAGE at your normal speed (path + duration are recorded)
3) PAGE 2 — click the new 6 portrait centers, then Save & exit

Writes debug_out/roster_clicks_*/clicks.json and data/roster_page_jump.json
(timed path replay for the scraper).
"""
from __future__ import annotations

import json
import statistics
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
EXPECTED_SLOTS = 6


class RosterClickRecorder:
    def __init__(self) -> None:
        self.root = tk.Tk()
        self.root.title("Roster click recorder")
        self.root.attributes("-topmost", True)
        self.root.geometry("500x280+40+40")
        self.root.resizable(False, False)

        self.status = tk.StringVar(
            value="Overview at TOP? Press Start, then click page-1 portraits."
        )
        self.step = tk.StringVar(value="Idle")
        self.last = tk.StringVar(value="")

        tk.Label(self.root, textvariable=self.status, wraplength=480, justify="left").pack(
            anchor="w", padx=10, pady=(10, 4)
        )
        tk.Label(self.root, textvariable=self.step, font=("Segoe UI", 11, "bold")).pack(
            anchor="w", padx=10, pady=4
        )
        tk.Label(self.root, textvariable=self.last, fg="#444", wraplength=480).pack(
            anchor="w", padx=10, pady=2
        )

        row = tk.Frame(self.root)
        row.pack(fill="x", padx=10, pady=10)
        self.btn_start = tk.Button(row, text="Start", width=12, command=self.start)
        self.btn_start.pack(side="left", padx=2)
        self.btn_page_done = tk.Button(
            row, text="Page done", width=12, state="disabled", command=self.request_page_done
        )
        self.btn_page_done.pack(side="left", padx=2)
        self.btn_save = tk.Button(
            row, text="Save & exit", width=12, state="disabled", command=self.request_save
        )
        self.btn_save.pack(side="left", padx=2)

        self._ox = self._oy = 0
        self._res = (2560, 1440)
        self._pages: list[list[list[int]]] = [[], []]
        # phases: page1 | scroll | page2 | done
        self._phase = "page1"
        self._scroll_drag: dict | None = None
        self._cmd: str | None = None  # page_done | save — set by UI thread
        self._stop = False
        self._our_hwnds: set[int] = set()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _refresh_hwnds(self) -> None:
        """Collect this window's hwnd tree so button clicks are never recorded as slots."""
        import win32gui

        hwnds: set[int] = set()
        root_hwnd = int(self.root.winfo_id())

        def enum_child(hwnd, _):
            hwnds.add(int(hwnd))
            return True

        hwnds.add(root_hwnd)
        try:
            win32gui.EnumChildWindows(root_hwnd, enum_child, None)
        except Exception:
            pass
        # Tk on Windows sometimes nests under a wrapper
        try:
            parent = win32gui.GetParent(root_hwnd)
            for _ in range(4):
                if not parent:
                    break
                hwnds.add(int(parent))
                parent = win32gui.GetParent(parent)
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
        self._pages = [[], []]
        self._phase = "page1"
        self._scroll_drag = None
        self._cmd = None
        self._stop = False
        self.btn_start.config(state="disabled")
        self.btn_page_done.config(state="normal")
        self.btn_save.config(state="normal")
        self.status.set(
            f"PAGE 1: click {EXPECTED_SLOTS} portrait centers (top→bottom), then Page done."
        )
        self.step.set(f"Page 1 — slot 1 / {EXPECTED_SLOTS}")
        threading.Thread(target=self._run, daemon=True).start()

    def request_page_done(self) -> None:
        self._refresh_hwnds()
        self._cmd = "page_done"
        self.last.set("Page done pressed…")

    def request_save(self) -> None:
        self._cmd = "save"
        self.last.set("Saving…")

    def _on_close(self) -> None:
        self._stop = True
        self._cmd = "save"
        if any(self._pages) or self._scroll_drag:
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

    def _pump_cmd(self) -> str | None:
        cmd = self._cmd
        if cmd:
            self._cmd = None
        return cmd

    def _wait_click(self) -> tuple[int, int] | None:
        """Wait for a game click. Returns None if cmd/abort interrupts."""
        import win32api
        import win32gui

        while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
            time_mod.sleep(0.02)
        while not self._stop:
            cmd = self._pump_cmd()
            if cmd:
                # put it back for the main loop
                self._cmd = cmd
                return None
            if win32api.GetAsyncKeyState(ABORT_VK) & 0x8000:
                self._stop = True
                return None
            if win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                x, y = win32gui.GetCursorPos()
                hwnd = win32gui.WindowFromPoint((x, y))
                on_ui = self._on_our_ui(hwnd)
                while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                    time_mod.sleep(0.02)
                if on_ui:
                    continue
                return int(x - self._ox), int(y - self._oy)
            time_mod.sleep(0.02)
        return None

    def _wait_drag(self) -> dict | None:
        """Record one LBUTTON drag with path samples + wall-clock duration."""
        import win32api
        import win32gui

        self.root.after(
            0,
            lambda: self.status.set(
                "SCROLL: drag the RIGHT portrait column ONE PAGE at your normal speed "
                "(duration is recorded)."
            ),
        )
        self.root.after(0, lambda: self.step.set("Hold-drag on roster (timing recorded)"))

        while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
            time_mod.sleep(0.02)

        while not self._stop:
            cmd = self._pump_cmd()
            if cmd == "save":
                self._cmd = cmd
                return None
            if cmd == "page_done":
                return {"skipped": True}
            if win32api.GetAsyncKeyState(ABORT_VK) & 0x8000:
                self._stop = True
                return None
            if win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                x0, y0 = win32gui.GetCursorPos()
                hwnd = win32gui.WindowFromPoint((x0, y0))
                if self._on_our_ui(hwnd):
                    while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                        time_mod.sleep(0.02)
                    continue
                t0 = time_mod.perf_counter()
                start = [int(x0 - self._ox), int(y0 - self._oy)]
                samples = [{"t": 0.0, "x": start[0], "y": start[1]}]
                self.root.after(
                    0,
                    lambda s=start: self.last.set(f"drag start ({s[0]},{s[1]}) — keep holding…"),
                )
                while win32api.GetAsyncKeyState(LBUTTON_VK) & 0x8000:
                    x, y = win32gui.GetCursorPos()
                    samples.append(
                        {
                            "t": round(time_mod.perf_counter() - t0, 4),
                            "x": int(x - self._ox),
                            "y": int(y - self._oy),
                        }
                    )
                    time_mod.sleep(0.008)
                duration = round(time_mod.perf_counter() - t0, 4)
                x1, y1 = win32gui.GetCursorPos()
                end = [int(x1 - self._ox), int(y1 - self._oy)]
                if samples[-1]["x"] != end[0] or samples[-1]["y"] != end[1]:
                    samples.append({"t": duration, "x": end[0], "y": end[1]})
                # Collapse near-duplicate samples to keep JSON small.
                slim = [samples[0]]
                for s in samples[1:]:
                    prev = slim[-1]
                    if abs(s["x"] - prev["x"]) + abs(s["y"] - prev["y"]) >= 2:
                        slim.append(s)
                if slim[-1] is not samples[-1]:
                    slim.append(samples[-1])
                drag = {
                    "start": start,
                    "end": end,
                    "deltaY": end[1] - start[1],
                    "deltaX": end[0] - start[0],
                    "durationS": duration,
                    "sampleCount": len(slim),
                    "samples": slim,
                }
                self.root.after(
                    0,
                    lambda d=drag: self.last.set(
                        f"drag Δy={d['deltaY']} in {d['durationS']}s "
                        f"({d['start']} → {d['end']}, {d['sampleCount']} pts)"
                    ),
                )
                return drag
            time_mod.sleep(0.02)
        return None

    def _handle_page_done(self) -> None:
        if self._phase == "page1":
            if len(self._pages[0]) < 2:
                self.root.after(
                    0, lambda: self.status.set("Need at least 2 clicks on page 1.")
                )
                return
            self._phase = "scroll"
            self.root.after(
                0,
                lambda: self.status.set(
                    f"Page 1 OK ({len(self._pages[0])} slots). Now SCROLL one page…"
                ),
            )
        elif self._phase == "page2":
            if len(self._pages[1]) < 2:
                self.root.after(
                    0, lambda: self.status.set("Need at least 2 clicks on page 2.")
                )
                return
            self._phase = "done"
            self.root.after(0, lambda: self.step.set("Done — Save & exit"))
            self.root.after(
                0,
                lambda: self.status.set("Both pages captured. Save & exit."),
            )
            self.root.after(0, lambda: self.btn_page_done.config(state="disabled"))
        elif self._phase == "scroll":
            # Skip scroll → go to page2
            self._scroll_drag = {"skipped": True}
            self._phase = "page2"
            self.root.after(
                0,
                lambda: self.status.set(
                    f"PAGE 2: click {EXPECTED_SLOTS} portrait centers, then Page done / Save."
                ),
            )

    def _run(self) -> None:
        while not self._stop and self._phase != "done":
            cmd = self._pump_cmd()
            if cmd == "save":
                break
            if cmd == "page_done":
                self._handle_page_done()
                continue

            if self._phase == "scroll":
                drag = self._wait_drag()
                if drag is None and self._cmd == "save":
                    break
                if drag is not None:
                    self._scroll_drag = drag
                    self._phase = "page2"
                    self.root.after(
                        0,
                        lambda: self.status.set(
                            f"PAGE 2: click {EXPECTED_SLOTS} centers top→bottom, then Page done."
                        ),
                    )
                    self.root.after(
                        0, lambda: self.step.set(f"Page 2 — slot 1 / {EXPECTED_SLOTS}")
                    )
                continue

            if self._phase not in ("page1", "page2"):
                time_mod.sleep(0.05)
                continue

            page_i = 0 if self._phase == "page1" else 1
            n = len(self._pages[page_i]) + 1
            self.root.after(
                0,
                lambda p=page_i + 1, n=n: self.step.set(
                    f"Page {p} — slot {n} / {EXPECTED_SLOTS}"
                ),
            )
            pt = self._wait_click()
            cmd = self._pump_cmd()
            if cmd == "save":
                break
            if cmd == "page_done":
                self._handle_page_done()
                continue
            if pt is None:
                continue

            # Phase may have changed while waiting
            if self._phase not in ("page1", "page2"):
                continue
            page_i = 0 if self._phase == "page1" else 1
            self._pages[page_i].append([pt[0], pt[1]])
            self.root.after(
                0,
                lambda p=page_i + 1, n=len(self._pages[page_i]), pt=pt: self.last.set(
                    f"page{p} slot{n} = ({pt[0]},{pt[1]})"
                ),
            )
            if len(self._pages[page_i]) >= EXPECTED_SLOTS:
                # Auto-advance hint — user still presses Page done, or we auto-fire
                self.root.after(0, self.request_page_done)

        self._save()
        self.root.after(0, lambda: self.step.set("Saved"))
        self.root.after(200, self.root.destroy)

    def finish(self) -> None:
        self.request_save()

    def _page_stats(self, slots: list[list[int]]) -> dict | None:
        if len(slots) < 2:
            return None
        ordered = sorted(slots, key=lambda p: p[1])
        xs = [p[0] for p in ordered]
        oys = [p[1] for p in ordered]
        deltas = [oys[i + 1] - oys[i] for i in range(len(oys) - 1)]
        step = int(round(statistics.median(deltas))) if deltas else 180
        x = int(round(statistics.median(xs)))
        return {
            "orderedSlots": ordered,
            "rightSide": [x, int(oys[0])],
            "step": step,
            "rosterSlots": len(ordered),
            "rosterSlotYs": oys,
            "deltas": deltas,
        }

    def _optimize(self) -> dict:
        p1 = self._page_stats(self._pages[0])
        p2 = self._page_stats(self._pages[1])
        base = p1 or p2
        if not base:
            return {"pages": self._pages, "scrollDrag": self._scroll_drag, "optimized": {}, "gameROI": {}}

        x, y0 = base["rightSide"]
        step = base["step"]
        if p1 and p2 and abs(p1["step"] - p2["step"]) <= 20:
            step = int(round((p1["step"] + p2["step"]) / 2))
            x = int(round((p1["rightSide"][0] + p2["rightSide"][0]) / 2))

        scroll = self._scroll_drag or {}
        pageJumpDrag = None
        durationS = None
        samples = None
        if scroll and not scroll.get("skipped") and "deltaY" in scroll:
            pageJumpDrag = int(scroll["deltaY"])
            durationS = scroll.get("durationS")
            samples = scroll.get("samples")

        return {
            "pages": {"page1": self._pages[0], "page2": self._pages[1]},
            "scrollDrag": self._scroll_drag,
            "page1_stats": p1,
            "page2_stats": p2,
            "optimized": {
                "rightSide": [x, y0],
                "offsets.rightSide.y": step,
                "rosterSlots": base["rosterSlots"],
                "rosterSlotYs": base["rosterSlotYs"],
                "pageJumpDrag": pageJumpDrag,
                "pageJumpDurationS": durationS,
                "scrollStart": scroll.get("start"),
                "scrollEnd": scroll.get("end"),
                "scrollSamples": samples,
            },
            "gameROI": {
                "rightSide": f"Coordinates({x}, {y0})",
                "offsets.rightSide": f"Coordinates(y={step})",
                "rosterSlots": base["rosterSlots"],
                "rosterSlotYs": base["rosterSlotYs"],
                "pageJumpDrag": pageJumpDrag,
                "pageJumpDurationS": durationS,
            },
        }

    def _save(self) -> None:
        out = ROOT / "debug_out" / f"roster_clicks_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        out.mkdir(parents=True, exist_ok=True)
        report = {
            "out": str(out),
            "resolution": list(self._res),
            **self._optimize(),
        }
        (out / "clicks.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        (ROOT / "debug_out" / "_latest_roster_clicks.txt").write_text(str(out), encoding="utf-8")
        # Also dump timed scroll path for the scraper to load without bloating gameROI.
        scroll = self._scroll_drag or {}
        if scroll and not scroll.get("skipped"):
            (out / "page_jump_path.json").write_text(
                json.dumps(
                    {
                        "start": scroll.get("start"),
                        "end": scroll.get("end"),
                        "deltaY": scroll.get("deltaY"),
                        "durationS": scroll.get("durationS"),
                        "samples": scroll.get("samples") or [],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            (ROOT / "data" / "roster_page_jump.json").write_text(
                json.dumps(
                    {
                        "start": scroll.get("start"),
                        "end": scroll.get("end"),
                        "deltaY": scroll.get("deltaY"),
                        "durationS": scroll.get("durationS"),
                        "samples": scroll.get("samples") or [],
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
        opt = report.get("optimized") or {}
        rs = opt.get("rightSide") or [0, 0]
        msg = (
            f"Saved {out / 'clicks.json'}  → rightSide=({rs[0]},{rs[1]}) "
            f"step={opt.get('offsets.rightSide.y')} "
            f"jump={opt.get('pageJumpDrag')} in {opt.get('pageJumpDurationS')}s"
        )
        try:
            self.status.set(msg)
        except Exception:
            pass

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    RosterClickRecorder().run()
