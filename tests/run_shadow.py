"""`shadow spread=`（贴着轮廓走的阴影）的回归测试。

这个圆用 8 个点画、经过平滑后实际半径约 73（不是 80），
所以边界要按实测来取：填色到 y≈273，往下是投影。

用 blur=0 的硬边来做判据，边界清楚、不受模糊半径干扰。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text          # noqa: E402
from fyb.painter import render                 # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


BG = (244, 239, 230)
HEAD = "canvas 400x400\nbg #F4EFE6\n"
SHAPE = ("curve [200,120 257,143 280,200 257,257 200,280 143,257 "
         "120,200 143,143] fill=#D9C36E stroke=none closed name=blob\n")


def scene(shadow_line: str) -> str:
    return HEAD + (shadow_line + "\n" if shadow_line else "") + SHAPE


def px(src: str, x: int, y: int):
    r = compile_text(src)
    assert r.ok, [(e.code, e.message) for e in r.errors]
    cv = render(r.scene, scale=1)
    c = cv.img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def is_bg(c, tol=6):
    return all(abs(a - b) <= tol for a, b in zip(c, BG))


def has(cond_line, x, y):
    return not is_bg(px(scene(cond_line), x, y))


# 实测边界：填色到 y≈273
NEAR = 280      # 距边缘 7px
FAR = 292       # 距边缘 19px

# 1) 硬边 + spread=10：7px 处有投影，19px 处没有
s10 = "shadow ref=blob dx=0 dy=0 spread=10 blur=0 alpha=0.85 color=#2A211A"
check("spread=10：紧贴轮廓 7px 处有投影", has(s10, 200, NEAR),
      f"{px(scene(s10), 200, NEAR)}")
check("spread=10：19px 处已出界", is_bg(px(scene(s10), 200, FAR)),
      f"{px(scene(s10), 200, FAR)}")

# 2) 同一条线但 spread=0：7px 处应该是底色（证明 spread 真在起作用）
s0 = "shadow ref=blob dx=0 dy=0 spread=0 blur=0 alpha=0.85 color=#2A211A"
check("spread=0：7px 处仍是底色", is_bg(px(scene(s0), 200, NEAR)),
      f"{px(scene(s0), 200, NEAR)}")

# 3) spread 越大，外扩越远：spread=30 时 19px 处也在投影里
s30 = "shadow ref=blob dx=0 dy=0 spread=30 blur=0 alpha=0.85 color=#2A211A"
check("spread=30：19px 处也在投影里", has(s30, 200, FAR),
      f"{px(scene(s30), 200, FAR)}")

# 4) 软边（blur）也能贴轮廓
soft = "shadow ref=blob dx=0 dy=0 spread=12 blur=6 alpha=0.7 color=#2A211A"
check("spread + blur：贴轮廓一圈是灰的", has(soft, 200, 288),
      f"{px(scene(soft), 200, 288)}")

# 5) 老的 dx/dy 偏移没被破坏
offset = "shadow ref=blob dx=24 dy=24 blur=8 alpha=0.7 color=#2A211A"
check("老的 dx/dy 偏移照旧", has(offset, 224, 224), f"{px(scene(offset), 224, 224)}")

# 6) 参数校验
r = compile_text(scene("shadow ref=blob spread=999"))
check("spread 超范围被拒", (not r.ok) and "spread" in r.errors[0].message,
      str([(e.code, e.message[:40]) for e in r.errors]))
r = compile_text(scene("shadow ref=blob spread=-5"))
check("spread 负数被拒", not r.ok, str([(e.code, e.message[:40]) for e in r.errors]))
r = compile_text(scene("shadow ref=blob spread=abc"))
check("spread 非数字被拒", not r.ok, str([(e.code, e.message[:40]) for e in r.errors]))

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
