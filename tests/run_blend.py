"""混合模式的回归测试。跑法：python tests/run_blend.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text          # noqa: E402
from fyb.painter import render                 # noqa: E402

fails: list[str] = []
C = "canvas 200x200\nbg #ffffff\n"


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


def codes(src):
    return [e.code for e in compile_text(src).errors]


check("坏模式报 E012", "E012" in codes(C + "blend 不认识\n"))
check("缺 endblend 报 E006", "E006" in codes(C + "blend multiply\ncircle 50,50,20 fill=#333\n"))
check("endblend 多了报 E006", "E006" in codes(C + "endblend\n"))

# 像素级：multiply 必须比 normal 暗，screen 必须比 normal 亮
def pixel(src, x, y):
    r = compile_text(src)
    assert r.ok, [e.code for e in r.errors]
    cv = render(r.scene, scale=1)
    c = cv.img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


base = C + "circle 100,100,80 fill=#F0561C\n"
lone = pixel(base + "circle 100,100,80 fill=#2060C0\n", 100, 100)

mul = pixel(base + "blend multiply\ncircle 100,100,80 fill=#2060C0\nendblend\n", 100, 100)
scr = pixel(base + "blend screen\ncircle 100,100,80 fill=#2060C0\nendblend\n", 100, 100)

# normal：后画的直接盖上（等于单独画蓝圆）
check("normal 就是覆盖", lone == pixel(base + "circle 100,100,80 fill=#2060C0\n", 100, 100),
      f"{lone}")
# 橙 × 蓝：整体压暗，且每个通道都不该变亮
check("multiply 变暗",
      sum(mul) < sum(lone) * 0.6 and all(m <= n + 2 for m, n in zip(mul, lone)),
      f"normal={lone} multiply={mul}")
# screen：至少一个通道被提亮
check("screen 变亮", sum(scr) > sum(lone), f"normal={lone} screen={scr}")

# 嵌套：内层生效
nest = pixel(base + "blend multiply\nblend screen\ncircle 100,100,80 fill=#2060C0\n"
                   "endblend\nendblend\n", 100, 100)
check("嵌套取最内层", nest != mul and nest != lone, f"nest={nest} mul={mul}")

# 块外不受影响
outside = pixel(base + "blend multiply\ncircle 100,100,80 fill=#2060C0\nendblend\n"
                      "rect 180,180,20,20 fill=#FFFFFF\n", 190, 190)
check("块外恢复 normal", outside == (255, 255, 255), f"{outside}")

# 关键回归：blend 块之后的普通图元必须用 normal 画。
# 之前 render() 给每个图元新建状态字典，字典说 normal、画笔还停在 screen，
# 于是不会重置 —— 一整片画面被上一个 blend 块洗白（室内那张就是这么翻车的）。
after = pixel(C + "rect 20,20,160,160 fill=#804020\n"
                   "blend screen\nrect 0,0,200,100 fill=#FFFFFF alpha=0.4\nendblend\n"
                   "rect 40,120,40,40 fill=#804020\n", 60, 140)
check("blend 块之后的图元不串味", after == (128, 64, 32), f"{after}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
