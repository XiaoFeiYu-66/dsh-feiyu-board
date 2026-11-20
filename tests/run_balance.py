"""构图体检的回归测试。

用合成图，不依赖场景：
  ① 全白空画布      → 覆盖率 ≈ 0，报"整张几乎是空的"
  ② 左上角一个方块  → 右下角空、重心偏左上
  ③ 铺满            → 覆盖率 ≈ 1，报"压得太满"
  ④ 中间一条横带    → 上下两行都空
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PIL import Image

from fyb.balance import analyze, format_grid, image_to_array  # noqa: E402
from PySide6.QtGui import QImage                                # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


def qimage_of(pil_img) -> QImage:
    rgb = pil_img.convert("RGB")
    w, h = rgb.size
    data = rgb.tobytes()
    return QImage(data, w, h, w * 3, QImage.Format_RGB888).copy()


def blank(w=400, h=300) -> Image.Image:
    return Image.new("RGB", (w, h), (255, 255, 255))


def box(img, x0, y0, x1, y1, color=(30, 30, 30)):
    px = img.load()
    for y in range(y0, y1):
        for x in range(x0, x1):
            px[x, y] = color
    return img


# ① 空画布
b = analyze(qimage_of(blank()))
check("空画布：覆盖率接近 0", b.coverage < 0.01, f"{b.coverage:.3f}")
check("空画布：会提醒整张是空的",
      any("几乎是空" in n for n in b.notes), str(b.notes))

# ② 左上角一个方块
img = box(blank(), 20, 20, 140, 120)
b = analyze(qimage_of(img), cols=4, rows=3)
check("左上块：左上格有墨", b.grid[0][0] > 0.3, f"{b.grid[0][0]:.2f}")
check("左上块：右下角是空的", b.grid[2][3] < 0.03, f"{b.grid[2][3]:.2f}")
check("左上块：重心偏左上", b.centroid[0] < 0.5 and b.centroid[1] < 0.5,
      f"{b.centroid}")
check("左上块：有关于空的提示", bool(b.notes), str(b.notes))

# ③ 铺满
b = analyze(qimage_of(box(blank(), 0, 0, 400, 300)))
check("铺满：覆盖率接近 1", b.coverage > 0.95, f"{b.coverage:.3f}")
check("铺满：会提醒压得太满", any("太满" in n for n in b.notes), str(b.notes))

# ④ 中间一条横带
img = box(blank(), 0, 120, 400, 180)
b = analyze(qimage_of(img), cols=4, rows=3)
check("横带：中间行有墨", b.grid[1][1] > 0.3, f"{b.grid[1][1]:.2f}")
check("横带：上排是空的", b.grid[0][0] < 0.03, f"{b.grid[0][0]:.2f}")
check("横带：下排是空的", b.grid[2][0] < 0.03, f"{b.grid[2][0]:.2f}")
check("横带：重心在垂直中线附近", abs(b.centroid[1] - 0.5) < 0.1, f"{b.centroid}")

# 文字表能出来、行数对
text = format_grid(b)
check("文字表有 3 行数据", len([ln for ln in text.splitlines() if ln.startswith("行")]) == 3,
      text)

# image_to_array 的尺寸要对
arr = image_to_array(qimage_of(blank(64, 48)))
check("像素数组尺寸对", arr.shape == (48, 64, 3), str(arr.shape))

# 底色不是白的：必须按底色量，否则满版画面会被算成 100%（踩过这个坑）
tinted = Image.new("RGB", (400, 300), (240, 226, 200))
box(tinted, 180, 130, 220, 170, (40, 40, 40))       # 中间一个小方块
b = analyze(qimage_of(tinted), cols=4, rows=3, bg=(240, 226, 200))
check("非白底：只算出那个小方块", b.coverage < 0.02, f"{b.coverage:.3f}")
check("非白底：不会误报太满", not any("太满" in n for n in b.notes), str(b.notes))
b_wrong = analyze(qimage_of(tinted), cols=4, rows=3, bg=(255, 255, 255))
check("底色传错才会变 100%（说明这个参数真的在用）", b_wrong.coverage > 0.9,
      f"{b_wrong.coverage:.3f}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
