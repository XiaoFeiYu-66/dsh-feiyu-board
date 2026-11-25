"""真图层（layer alpha= / blend= … endlayer）的回归测试。

判据是「交点该不该更深」：
- 块级 blend：每个图元都直接合成到底图上 → 走两笔的交点乘了两次，更深
- 真图层：层内先按 normal 叠在一起，最后整体合成一次 → 交点与单笔同色
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


HEAD = "canvas 400x300\nbg #FFFFFF\nhand preset=clean seed=8\n"
BASE = "rect 20,20,360,260 fill=#E8DFC8\n"
# 两条正交的粗笔，交点在 (200,150)
CROSS = ("ink [90,150 310,150] w=40 color=#7788AA jitter=0\n"
         "ink [200,60 200,240] w=40 color=#7788AA jitter=0\n")


def px(src: str, x: int, y: int):
    r = compile_text(src)
    assert r.ok, [(e.code, e.message) for e in r.errors]
    cv = render(r.scene, scale=1)
    c = cv.img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


def lum(c):
    return 0.299 * c[0] + 0.587 * c[1] + 0.114 * c[2]


CENTER = (200, 150)     # 交点
ON_X = (120, 150)       # 只在横笔上
OFF = (60, 60)          # 底图上（两支笔都碰不到）

# 1) 块级 blend：交点明显比单笔深
block = HEAD + BASE + "blend multiply\n" + CROSS + "endblend\n"
check("块级 blend：交点比单笔深",
      lum(px(block, *CENTER)) < lum(px(block, *ON_X)) - 10,
      f"交点 {lum(px(block, *CENTER)):.0f} vs 单笔 {lum(px(block, *ON_X)):.0f}")

# 2) 真图层：交点与单笔同色（只乘了一次）
layer = HEAD + BASE + "layer blend=multiply\n" + CROSS + "endlayer\n"
d = abs(lum(px(layer, *CENTER)) - lum(px(layer, *ON_X)))
check("真图层：交点与单笔几乎同色", d < 6,
      f"差 {d:.1f}（交点 {lum(px(layer, *CENTER)):.0f} / 单笔 {lum(px(layer, *ON_X)):.0f}）")

# 3) 真图层的 multiply 确实作用到了底图上（不是没生效）
check("真图层：multiply 确实压暗了底图",
      lum(px(layer, *ON_X)) < lum(px(layer, *OFF)) - 5,
      f"笔上 {lum(px(layer, *ON_X)):.0f} vs 底图 {lum(px(layer, *OFF)):.0f}")

# 4) layer alpha=0.5：整层半透明；层内重叠不会再加深
semi = HEAD + BASE + "layer alpha=0.5\n" + CROSS + "endlayer\n"
d2 = abs(lum(px(semi, *CENTER)) - lum(px(semi, *ON_X)))
check("layer alpha：层内重叠不加深", d2 < 6, f"差 {d2:.1f}")

# 5) 对照：两笔各自 alpha=0.5（不开图层）→ 交点更深
sep = HEAD + BASE + ("ink [90,150 310,150] w=40 color=#7788AA alpha=0.5 jitter=0\n"
                     "ink [200,60 200,240] w=40 color=#7788AA alpha=0.5 jitter=0\n")
check("对照：不开图层时半透明两笔会叠加变深",
      lum(px(sep, *CENTER)) < lum(px(sep, *ON_X)) - 8,
      f"交点 {lum(px(sep, *CENTER)):.0f} vs 单笔 {lum(px(sep, *ON_X)):.0f}")

# 6) 老写法 layer 5（z 序）仍然能编译
r = compile_text(HEAD + "layer 5\n" + BASE)
check("老的 layer 5 写法仍可用", r.ok,
      str([(e.code, e.message[:40]) for e in r.errors]))

# 7) 块没关 / 多余的 endlayer
r = compile_text(HEAD + "layer alpha=0.5\n" + BASE)
check("layer 没 endlayer 会报 E006",
      (not r.ok) and r.errors[0].code == "E006",
      str([(e.code, e.message[:40]) for e in r.errors]))
r = compile_text(HEAD + "endlayer\n" + BASE)
check("多余的 endlayer 会报 E006",
      (not r.ok) and r.errors[0].code == "E006",
      str([(e.code, e.message[:40]) for e in r.errors]))

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
