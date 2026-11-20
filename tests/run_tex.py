"""纹理笔的回归测试。跑法：python tests/run_tex.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text          # noqa: E402
from fyb.painter import render                 # noqa: E402
from fyb.texture import TEXTURES, get_tile     # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


C = "canvas 400x200\nbg #ffffff\n"


def codes(src):
    return [e.code for e in compile_text(src).errors]


def pixels(src):
    r = compile_text(src)
    assert r.ok, [(e.code, e.line) for e in r.errors]
    cv = render(r.scene, scale=1)
    img = cv.img
    out = []
    for y in range(img.height()):
        for x in range(img.width()):
            c = img.pixelColor(x, y)
            out.append((c.red(), c.green(), c.blue()))
    return np.array(out, dtype=np.float32)


# ── 纹理本身 ───────────────────────────────────────
check("四种纹理都能生成", all(get_tile(n, 5) is not None for n in TEXTURES))

# 跨进程必须一致。之前这里用了内置 hash(名字) 当种子，
# 而 Python 的字符串 hash 每进程随机化 → 每次渲染的纸纹都不一样，
# 把"同一 seed 出同一张"这条底线悄悄破了。这条测试专门盯着它。
import subprocess                                    # noqa: E402
code = ("import sys; sys.path.insert(0, %r)\n"
        "from fyb.texture import get_tile\n"
        "t = get_tile('paper', 7)\n"
        "print(t.pixelColor(10, 20).alpha(), t.pixelColor(100, 100).alpha())"
        % str(ROOT))
outs = [subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True).stdout.strip() for _ in range(2)]
check("纹理跨进程一致", outs[0] == outs[1] and bool(outs[0]), f"{outs}")
t = get_tile("dry", 5)
alphas = []
for y in range(0, 256, 7):
    for x in range(0, 256, 7):
        alphas.append(t.pixelColor(x, y).alpha())
check("dry 有真空洞（不是半透明）", min(alphas) < 20 and max(alphas) > 235,
      f"min={min(alphas)} max={max(alphas)}")
check("同一 seed 出同一张", get_tile("paper", 9).pixelColor(30, 40) ==
      get_tile("paper", 9).pixelColor(30, 40))
check("不同 seed 出不同", get_tile("paper", 9).pixelColor(30, 40) !=
      get_tile("paper", 10).pixelColor(30, 40))

# ── 命令层面 ───────────────────────────────────────
check("坏纹理名报 E012", "E012" in codes(C + "ink [10,10 200,60] tex=wood\n"))
check("tex=none 等于没纹理",
      len(compile_text(C + "ink [10,10 200,60] tex=none\n").errors) == 0)
check("passes 越界报 E007", "E007" in codes(C + "ink [10,10 200,60] passes=99\n"))

# ── 画出来真的不一样 ────────────────────────────────
STROKE = "ink [40,100 200,80 360,110] w=40 color=#223344 taper=0"
plain = pixels(C + STROKE + "\n")
paper = pixels(C + STROKE + " tex=paper\n")

# 同一块区域，带纹理后笔画内部的亮度应该不再是"一个平色"。
# 用"内部窗口里有多少个不同灰度"来量 —— 比方差稳：
# 加纹理时笔宽也会抖，边缘像素一多，方差反而可能变小。
def levels(arr, img_w=400, x0=185, y0=75, size=30):
    core = []
    for y in range(y0, y0 + size):
        for x in range(x0, x0 + size):
            r, g, b = arr[y * img_w + x]
            core.append(int(r) + int(g) + int(b))
    return len(set(core))


check("paper 让笔画内部不再是平色", levels(paper) > levels(plain) + 3,
      f"plain 有 {levels(plain)} 种灰度，paper 有 {levels(paper)} 种")

dry1 = pixels(C + STROKE + " tex=dry\n")


def coverage(arr):
    return float((arr.sum(axis=1) < 500).mean())


check("dry 会吃掉一部分笔迹", coverage(dry1) < coverage(plain) * 0.85,
      f"plain={coverage(plain):.3f} dry={coverage(dry1):.3f}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
