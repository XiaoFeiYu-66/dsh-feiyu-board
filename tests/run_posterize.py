"""`fyb posterize`（图片 → 按颜色分层的场景）的回归测试。

用合成图，不依赖任何外部素材：
  白底 + 红/绿/蓝三个方块 + 一个 5×5 的青色噪点
断言：三个方块都成了色块、噪点被丢掉、背景没被画成一块、
画布比例对、两次跑出来的文本完全一致（可复现）。
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text                      # noqa: E402
from fyb.posterize import vectorize                        # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


def make_fixture(path: Path) -> None:
    im = Image.new("RGB", (400, 300), (255, 255, 255))
    px = im.load()
    for y in range(20, 140):
        for x in range(20, 140):
            px[x, y] = (220, 30, 30)          # 红
    for y in range(160, 280):
        for x in range(20, 140):
            px[x, y] = (30, 180, 60)          # 绿
    for y in range(20, 280):
        for x in range(240, 380):
            px[x, y] = (40, 60, 200)          # 蓝
    for y in range(150, 155):
        for x in range(180, 185):
            px[x, y] = (0, 200, 200)          # 5×5 噪点，应该被丢掉
    im.save(str(path))


def regions_of(text: str):
    """从生成的场景里扒出 [(颜色 rgb, 点列)]。"""
    import re
    out = []
    for m in re.finditer(r"curve \[([^\]]+)\] fill=#([0-9A-Fa-f]{6})", text):
        color = (int(m.group(2)[0:2], 16), int(m.group(2)[2:4], 16),
                 int(m.group(2)[4:6], 16))
        pts = [tuple(float(v) for v in p.split(",")) for p in m.group(1).split()]
        out.append((color, pts))
    return out


def near(c, target, tol=34):
    return all(abs(a - b) <= tol for a, b in zip(c, target))


work = ROOT / "tests" / "_tmp_posterize"
work.mkdir(exist_ok=True)
img = work / "blocks.png"
make_fixture(img)

text, stats = vectorize(img, colors=8, blur=0.0, eps=1.2, height=300,
                        min_area=380, win=5)
regs = regions_of(text)

check("生成了色块", len(regs) >= 3, f"{len(regs)} 个")
check("画布比例对（400:300）", stats["width"] == 400 and stats["height"] == 300,
      f"{stats['width']}x{stats['height']}")

colors = [c for c, _ in regs]
check("有红色块", any(near(c, (220, 30, 30)) for c in colors), str(colors))
check("有绿色块", any(near(c, (30, 180, 60)) for c in colors), str(colors))
check("有蓝色块", any(near(c, (40, 60, 200)) for c in colors), str(colors))
check("噪点被丢掉（没有青色）", not any(near(c, (0, 200, 200)) for c in colors),
      str(colors))

# 背景不该被画成一个大色块（铺满画布的那些直接交给 bg）
huge = [c for c, pts in regs
        if (max(p[0] for p in pts) - min(p[0] for p in pts)) > 380
        and (max(p[1] for p in pts) - min(p[1] for p in pts)) > 280]
check("背景没被画成色块", not huge, str(huge))

# 红色块的位置要落在左上方
red = next((pts for c, pts in regs if near(c, (220, 30, 30))), None)
if red:
    xs = [p[0] for p in red]
    ys = [p[1] for p in red]
    check("红色块在左上",
          min(xs) < 60 and max(xs) < 180 and min(ys) < 60 and max(ys) < 170,
          f"x {min(xs):.0f}..{max(xs):.0f} y {min(ys):.0f}..{max(ys):.0f}")
else:
    check("红色块在左上", False, "没找到红色区域")

# 生成的场景要能编译
r = compile_text(text)
check("生成的场景能编译", r.ok, str([(e.code, e.line) for e in r.errors]))

# 可复现：同一张图跑两次，文本必须逐字相同
text2, stats2 = vectorize(img, colors=8, blur=0.0, eps=1.2, height=300,
                          min_area=380, win=5)
check("两次结果完全一致", text == text2 and stats == stats2)

# 参数要真的起作用：颜色数调小，色块不该更多
text3, stats3 = vectorize(img, colors=3, blur=0.0, eps=1.2, height=300,
                          min_area=380, win=5)
check("颜色数变少，色块不增加", stats3["regions"] <= stats["regions"],
      f"{stats3['regions']} vs {stats['regions']}")


# ── 多数表决（去麻点）要真的起作用 ───────────────────────────
# 干净硬边的图看不出这一步的作用，所以做一张"内部带随机抖动"的图：
# 不开表决时，同一块蓝会被量化成好几种色，碎成许多小块。
noisy = work / "noisy.png"
rng = np.random.default_rng(0)
im2 = Image.new("RGB", (300, 300), (255, 255, 255))
arr = np.asarray(im2).astype(np.int16).copy()
base = np.array([40, 60, 200], dtype=np.int16)
jitter = rng.integers(-28, 29, size=(200, 200, 3))
arr[50:250, 50:250] = np.clip(base + jitter, 0, 255)
Image.fromarray(arr.astype(np.uint8)).save(str(noisy))

_, s_raw = vectorize(noisy, colors=8, blur=0.0, eps=1.0, height=300,
                     min_area=60, win=1)
_, s_clean = vectorize(noisy, colors=8, blur=0.0, eps=1.0, height=300,
                       min_area=60, win=7)
# 看"最大一块有多大"：不清理时噪点会把整块打散成碎片，最大块很小；
# 清理之后应该合成一整块（接近 200×200 = 40000 px）。
check("多数表决把碎块合掉", s_clean["max_area"] > 4 * max(1, s_raw["max_area"]),
      f"win=1 最大块 {s_raw['max_area']} px，win=7 最大块 {s_clean['max_area']} px")
check("清理后应是一整块（约 4 万像素）", s_clean["max_area"] > 20000,
      f"{s_clean['max_area']} px")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
