"""定向纸纹（纹理跟着笔走）的回归测试。

判据：纹理的纤维若**顺着笔**，那么"横切笔身"采样的起伏会比"沿笔身"大得多。
所以横笔和竖笔都应该出现 cross/along ≫ 1，而且两个比值在同一量级。

如果纹理钉死在画布上（旧行为），横笔会是 ≫1，竖笔会反过来 ≪1 —— 这条测试能抓住。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text
from fyb.painter import render

SRC = """canvas 400x400
bg #FFFFFF
ink [60,100 340,100] w=60 color=#333333 tex=fiber tex_scale=0.5
ink [200,180 200,380] w=60 color=#333333 tex=fiber tex_scale=0.5
"""

fails: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


def profile(cv, cx, cy, vertical, half=50):
    vals = []
    for d in range(-half, half + 1):
        x, y = (cx, cy + d) if vertical else (cx + d, cy)
        vals.append(cv.img.pixelColor(x, y).red())
    return vals


def rough(vals):
    diffs = [abs(vals[i + 1] - vals[i]) for i in range(len(vals) - 1)]
    return sum(diffs) / max(1, len(diffs))


r = compile_text(SRC)
check("场景能编译", r.ok, str([(e.code, e.line) for e in r.errors]))
cv = render(r.scene, scale=1)

h_along = rough(profile(cv, 120, 100, vertical=False))
h_cross = rough(profile(cv, 120, 100, vertical=True))
v_along = rough(profile(cv, 200, 300, vertical=True))
v_cross = rough(profile(cv, 200, 300, vertical=False))

ratio_h = (h_cross + 0.01) / (h_along + 0.01)
ratio_v = (v_cross + 0.01) / (v_along + 0.01)
print(f"     横笔 顺 {h_along:.2f} / 横切 {h_cross:.2f} → {ratio_h:.2f}")
print(f"     竖笔 顺 {v_along:.2f} / 横切 {v_cross:.2f} → {ratio_v:.2f}")

check("横笔的纹路垂直于笔身（横切起伏更大）", ratio_h > 2.0, f"{ratio_h:.2f}")
check("竖笔也一样（说明纹理跟着笔转了）", ratio_v > 2.0, f"{ratio_v:.2f}")
check("两条笔的比值在同一量级",
      0.4 < ratio_h / max(0.01, ratio_v) < 2.5,
      f"横 {ratio_h:.2f} / 竖 {ratio_v:.2f}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
