"""量参考图的关键位置：脸、头发、眼睛、裙子。

手画这种图最大的问题是"比例全靠猜"，所以先把能量的量出来：
肤色区、深色头发区、白色褶边区、以及眼睛（深色瞳孔）的位置。
"""
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REF = sys.argv[1]

a = np.asarray(Image.open(REF).convert("RGB")).astype(np.int16)
h, w, _ = a.shape
print("图大小 %dx%d" % (w, h))
r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]

# 肤色：亮、偏暖（R 最大且大于 B）
skin = (r > 200) & (g > 165) & (b > 150) & (r - b > 12) & (r - g < 45)
# 头发：深蓝（B 明显大于 R，且不太亮）
hair = (b > 60) & (b - r > 30) & (r < 130)
# 白色（褶边、围裙）
white = (r > 225) & (g > 225) & (b > 225)
# 深色衣服：很暗
navy = (r < 90) & (g < 90) & (b < 110)


def bbox(mask, name, min_px=400):
    ys, xs = np.nonzero(mask)
    if len(ys) < min_px:
        print("  %-6s 太少（%d px）" % (name, len(ys)))
        return None
    print("  %-6s %6d px   x %4d..%4d  y %4d..%4d  中心(%d,%d)"
          % (name, len(ys), xs.min(), xs.max(), ys.min(), ys.max(),
             (xs.min() + xs.max()) // 2, (ys.min() + ys.max()) // 2))
    return (xs.min(), xs.max(), ys.min(), ys.max())


print("区域：")
bbox(hair, "头发")
bbox(skin, "皮肤")
bbox(white, "白")
bbox(navy, "深衣")

# 脸部里最暗的那块（眼睛的瞳孔）——只在皮肤 bbox 内找
sb = bbox(skin, "皮肤2", 100)
if sb:
    x0, x1, y0, y1 = sb
    sub_dark = (~skin[y0:y1, x0:x1]) & (r[y0:y1, x0:x1] < 120)
    ys, xs = np.nonzero(sub_dark)
    if len(ys):
        print("  眼区  x %4d..%4d  y %4d..%4d"
              % (xs.min() + x0, xs.max() + x0, ys.min() + y0, ys.max() + y0))

# 按行统计头发宽度，看看头部最宽在哪一行
rows = hair.sum(axis=1)
top = int(np.argmax(rows > 20))
wide = int(np.argmax(rows))
print("  头发从 y=%d 开始，最宽在 y=%d（宽 %d px）" % (top, wide, rows[wide]))
