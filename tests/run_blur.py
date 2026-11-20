"""软阴影 / 模糊的回归测试。跑法：python tests/run_blur.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text          # noqa: E402
from fyb.painter import render                 # noqa: E402

fails: list[str] = []
C = "canvas 300x200\nbg #ffffff\n"


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


def codes(src):
    return [e.code for e in compile_text(src).errors]


def shot(src):
    r = compile_text(src)
    assert r.ok, [(e.code, e.line) for e in r.errors]
    return render(r.scene, scale=1)


check("缺 endblur 报 E006", "E006" in codes(C + "blur 8\nrect 10,10,50,50 fill=#333\n"))
check("endblur 多了报 E006", "E006" in codes(C + "endblur\n"))
check("半径太小题 E007", "E007" in codes(C + "blur 0.1\nrect 1,1,9,9 fill=#333\nendblur\n"))

# 硬阴影 vs 软阴影：在阴影边界外一点采样，软阴影应当是"半透明"
hard = shot(C + """rect 60,40,100,100 fill=none stroke=none name=box
shadow ref=box dx=0 dy=0 alpha=0.8
""")
soft = shot(C + """rect 60,40,100,100 fill=none stroke=none name=box
shadow ref=box dx=0 dy=0 blur=16 alpha=0.8
""")
def px(cv, x, y):
    c = cv.img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())

# (58,90) 正好在盒子左边外 2px 处：硬阴影这里还是白的，软阴影已经被糊过去一点
h_out = px(hard, 58, 90)
s_out = px(soft, 58, 90)
check("软阴影会溢到轮廓外", s_out[0] < 250 and h_out[0] > 250,
      f"hard={h_out} soft={s_out}")

# 中心：两者都该是深灰
h_c, s_c = px(hard, 110, 90), px(soft, 110, 90)
check("阴影中心仍然是暗的", h_c[0] < 80 and s_c[0] < 120, f"hard={h_c} soft={s_c}")

# 清晰图元 vs 模糊块：中心的锐利边缘
sharp = shot(C + "rect 100,50,60,60 fill=#000000\n")
blurred = shot(C + "blur 12\nrect 100,50,60,60 fill=#000000\nendblur\n")
# 边界 (100,80) 附近：清晰图是纯黑，模糊后是深灰渐变
sp = px(sharp, 100, 80)
bp = px(blurred, 100, 80)
check("blur 块边缘变软", bp[0] > sp[0] + 20, f"sharp={sp} blurred={bp}")
# 中心仍黑
check("blur 块中心仍是黑的", px(blurred, 130, 80)[0] < 40, f"{px(blurred, 130, 80)}")

# 模糊块外侧没有被污染（层是整张画布，别漏到别处）
check("模糊块外侧干净", px(blurred, 5, 5)[0] > 250, f"{px(blurred, 5, 5)}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
