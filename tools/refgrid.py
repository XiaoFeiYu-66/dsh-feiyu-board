"""参考图垫格：给图盖上坐标网格，方便把"看到的"读成"坐标"。

用法：
    python tools/refgrid.py refs/room-construction.jpg --step 50

为什么要这一步：我没法边画边瞄着参考图，只能"看一次，读成数字，再画"。
盖上格子以后，读点就有了刻度，误差从"凭感觉"变成"±半格"。
"""
from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("image")
    ap.add_argument("--step", type=int, default=50, help="格子边长（像素）")
    ap.add_argument("--label", type=int, default=100, help="每隔多少标一次数字")
    ap.add_argument("--out", default=None)
    ap.add_argument("--scale", type=float, default=1.0, help="放大倍数（读小图用）")
    a = ap.parse_args()

    src = Path(a.image)
    img = Image.open(src).convert("RGB")
    if a.scale != 1.0:
        img = img.resize((int(img.width * a.scale), int(img.height * a.scale)),
                         Image.LANCZOS)
    d = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype("consola.ttf", 13)
    except OSError:
        font = ImageFont.load_default()

    step = a.step
    for x in range(0, img.width, step):
        major = (x % a.label == 0)
        d.line([(x, 0), (x, img.height)],
               fill=(255, 60, 60, 150) if major else (120, 160, 255, 90), width=1)
        if major:
            d.text((x + 2, 2), str(x), font=font, fill=(200, 0, 0, 255))
    for y in range(0, img.height, step):
        major = (y % a.label == 0)
        d.line([(0, y), (img.width, y)],
               fill=(255, 60, 60, 150) if major else (120, 160, 255, 90), width=1)
        if major:
            d.text((2, y + 1), str(y), font=font, fill=(200, 0, 0, 255))

    out = Path(a.out) if a.out else ROOT / "renders" / f"_grid_{src.stem}.png"
    img.save(out)
    print(f"{out}  {img.width}×{img.height}  格距 {step}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
