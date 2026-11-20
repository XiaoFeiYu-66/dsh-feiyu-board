"""按参考逐点描一只手的场景（临摹，不是生成）。

坐标是**参考图原始像素**，脚本负责把它们换算到画布：canvas 坐标 = (原图 - 裁切原点) × 倍率。
好处：以后要改某个点，直接改参考图上的数字，不用反算。

参考：refs/hands.jpg 左上那只张开的手（裁切 40,110 → 240,310，放大 6×）
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CROP = (40, 110)          # 裁切原点（原图像素）
K = 6                     # 放大倍数
SIZE = 1200               # 画布边长 = 200 × 6

# ── 从参考图上读出来的点（原图像素坐标）─────────────────
CONTOUR = [
    (97, 272), (92, 254), (86, 236), (81, 220),            # 腕 → 掌根
    (74, 212), (66, 204), (57, 196), (49, 190),            # 拇指外侧
    (45, 197), (48, 206), (57, 214), (68, 222),            # 拇指头 + 内侧
    (78, 228), (84, 220), (90, 206), (93, 196),            # 虎口回到食指根
    (94, 178), (96, 158), (98, 142), (99, 131),            # 食指左
    (103, 127), (107, 132), (108, 146), (109, 162), (110, 178),   # 食指头 + 右
    (112, 182), (114, 166), (116, 148), (118, 133), (120, 123),   # 中指左
    (125, 120), (129, 126), (130, 142), (130, 160), (129, 174),   # 中指头 + 右
    (132, 180), (136, 166), (140, 152), (145, 140), (149, 132),   # 无名指左
    (154, 130), (157, 138), (156, 152), (154, 166), (152, 178),   # 无名指头 + 右
    (154, 186), (160, 176), (166, 168), (172, 164), (176, 164),   # 小指左
    (180, 170), (178, 180), (172, 190), (166, 196),               # 小指头 + 右
    (168, 206), (170, 222), (166, 240), (160, 258), (154, 272),   # 右掌边 → 腕
]

FOLDS = [
    [(96, 216), (110, 226), (126, 232), (140, 230), (150, 226)],  # 掌横纹
    [(104, 246), (120, 256), (136, 258)],                         # 掌横纹下
    [(84, 214), (98, 220)],                                       # 拇指根
    [(99, 131), (104, 133), (110, 138)],                          # 食指节
    [(120, 123), (125, 125), (130, 130)],                         # 中指节
    [(149, 132), (153, 136)],                                     # 无名指节
    [(176, 164), (177, 172)],                                     # 小指节
]


def to_canvas(x: float, y: float) -> tuple[float, float]:
    return ((x - CROP[0]) * K, (y - CROP[1]) * K)


def fmt(pts):
    return " ".join(f"{cx:.0f},{cy:.0f}" for cx, cy in (to_canvas(x, y) for x, y in pts))


def build() -> str:
    outline = fmt(CONTOUR)
    folds = "\n".join(
        f'curve [{fmt(f)}] w={7 if i < 3 else 5} stroke=$淡 tex=paper '
        f'tex_scale=0.4 alpha={0.85 if i < 2 else 0.8} jitter=0.5 taper=0.5'
        for i, f in enumerate(FOLDS))
    return f"""canvas {SIZE}x{SIZE}
bg #F2ECDF

# 临摹：refs/hands.jpg 左上那只手，按原图像素逐点描，坐标由 tools/trace_hand.py 换算
# 对照用：python -m fyb render scenes/hand-trace.fyb --under refs/hands-crop.jpg
hand preset=pencil seed=77

let 铅 = #3B342B
let 淡 = #8A7F6E

curve [{outline}] w=8 stroke=$铅 closed tex=paper tex_scale=0.4 jitter=0.5 taper=0

{folds}

text 40,60 "手 · 临摹" 24 align=left color=$淡 hand=0.4
"""


if __name__ == "__main__":
    out = ROOT / "scenes" / "hand-trace.fyb"
    out.write_text(build(), encoding="utf-8")
    print(f"wrote {out}")
