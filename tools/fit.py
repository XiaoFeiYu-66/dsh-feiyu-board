"""精确排版：先把模板组按 1 倍画在原点，量出真包围盒，再解出 scale / at。

`use` 的变换是 p' = p*s + at，所以包围盒随 s 线性变化 —— 量一次就能解。
"""
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from fyb.compiler import compile_text
from fyb.painter import render
from fyb.balance import image_to_array

SRC = ROOT / "scenes" / "branch-full.fyb"

# 画布 2200 见方，把整株按 1 倍摆在原点，量真包围盒
big = """canvas 2200x2200
bg #FDFCF8
hand preset=pencil seed=53
"""
body = SRC.read_text(encoding="utf-8")
# 取模板定义（从 group name=叶 到 endgroup 链），把 use 株 换成 1 倍原点
start = body.index("let 线")
end = body.index("# ── 主株")
defs = body[start:end]
probe = big + defs + "\nuse 株 at=[0,0] scale=1\n"

r = compile_text(probe)
if not r.ok:
    print("探测场景编译失败", [(e.code, e.line) for e in r.errors])
    raise SystemExit(1)
cv = render(r.scene, scale=1)
a = image_to_array(cv.img).astype(np.int16)
ink = np.abs(a - a[1, 1]).max(axis=2) > 10
ys, xs = np.nonzero(ink)
x0, x1, y0, y1 = xs.min(), xs.max(), ys.min(), ys.max()
print("模板真包围盒  x %d..%d (宽 %d)  y %d..%d (高 %d)"
      % (x0, x1, x1 - x0, y0, y1, y1 - y0))

# 目标：画布 1100x1400，画区上方到题签线 y=1150，留 50 边距
W, H, TOP, BOTTOM, MARGIN = 1100, 1400, 50, 1120, 50
avail_w, avail_h = W - 2 * MARGIN, BOTTOM - TOP
s = min(avail_w / (x1 - x0), avail_h / (y1 - y0))
ax = W / 2 - (x0 + x1) / 2 * s
ay = TOP - y0 * s
print("解出 scale=%.3f  at=[%.0f,%.0f]" % (s, ax, ay))
print("预计墨迹 x %.0f..%.0f  y %.0f..%.0f"
      % (x0 * s + ax, x1 * s + ax, y0 * s + ay, y1 * s + ay))

text = SRC.read_text(encoding="utf-8")
text = re.sub(r"use 株 at=\[[^\]]+\] scale=[0-9.]+",
              "use 株 at=[%d,%d] scale=%.2f" % (round(ax), round(ay), s), text)
SRC.write_text(text, encoding="utf-8")
print("已写回", SRC.name)
