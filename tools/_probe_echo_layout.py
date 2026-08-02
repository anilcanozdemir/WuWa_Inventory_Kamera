from pathlib import Path
import numpy as np
from PIL import Image

p2 = Path(
    r"C:\Users\white\.cursor\projects\c-Users-white-Projects-wuwa-inventory-kamera"
    r"\assets\c__Users_white_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images"
    r"\image-2303a47f-d8e9-450d-a6f9-284cfe72ebcd.png"
)
p1 = Path(
    r"C:\Users\white\.cursor\projects\c-Users-white-Projects-wuwa-inventory-kamera"
    r"\assets\c__Users_white_AppData_Roaming_Cursor_User_workspaceStorage_empty-window_images"
    r"\image-4e72ff1d-cbf6-4dd0-80e6-3a2f3174bc27.png"
)
sx, sy = 2560 / 1024, 1440 / 575
im2 = np.array(Image.open(p2).convert("RGB"))
im1 = np.array(Image.open(p1).convert("RGB"))
out = Path("debug_out/echo_layout_probe")
out.mkdir(parents=True, exist_ok=True)


def crop_scaled(im, x, y, ww, hh, name):
    x0, y0 = int(x / sx), int(y / sy)
    x1, y1 = int((x + ww) / sx), int((y + hh) / sy)
    c = im[y0:y1, x0:x1]
    Image.fromarray(c).save(out / f"{name}.png")
    print(name, "src", x0, y0, x1 - x0, y1 - y0, "game", x, y, ww, hh)


for i, (x, y) in enumerate(
    [(1997, 354), (2100, 520), (2180, 700), (2100, 880), (1990, 1050)]
):
    crop_scaled(im1, x - 40, y - 40, 80, 80, f"ov_slot{i}")

for i, y in enumerate([380, 520, 660, 800, 950]):
    crop_scaled(im2, 120, y - 40, 100, 80, f"det_slot{i}")

for name, box in [
    ("name_inv", (1728, 152, 744, 80)),
    ("name_tight", (1900, 140, 520, 70)),
    ("level", (2200, 140, 120, 60)),
    ("level2", (2100, 200, 150, 50)),
    ("sonata_bottom", (1900, 1180, 400, 80)),
    ("full_right_top", (1850, 120, 650, 200)),
    ("equipped_sonata_line", (1850, 1100, 600, 100)),
]:
    crop_scaled(im2, *box, name)

print("wrote", out.resolve())
