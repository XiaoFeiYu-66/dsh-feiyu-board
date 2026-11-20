"""按形状的渐变（grad ref）与自定义渐变轴的回归测试。"""
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


def px(src, x, y):
    r = compile_text(src)
    assert r.ok, [(e.code, e.line) for e in r.errors]
    cv = render(r.scene, scale=1)
    c = cv.img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


C = "canvas 200x200\nbg #ffffff\n"

# 形状是圆，渐变必须被裁进圆里
SHAPE = C + ("circle 100,100,50 fill=none stroke=none name=b\n"
             "grad ref=b from=#ff0000 to=#0000ff p0=[50,100] p1=[150,100]\n")
inside = px(SHAPE, 100, 100)
outside = px(SHAPE, 100, 30)
corner = px(SHAPE, 20, 20)
check("形状内：中间有颜色", inside != (255, 255, 255), f"{inside}")
check("形状外：圆上方是白的", outside == (255, 255, 255), f"{outside}")
check("形状外：角落是白的", corner == (255, 255, 255), f"{corner}")

# 自定义轴：p0 在左、p1 在右 → 左边偏红、右边偏蓝
left = px(SHAPE, 60, 100)
right = px(SHAPE, 140, 100)
check("轴渐变：左侧偏红", left[0] > left[2], f"{left}")
check("轴渐变：右侧偏蓝", right[2] > right[0], f"{right}")

# 不给 p0/p1 时退回"包围盒 + 角度"，dir=0 应该是横向
H = C + ("circle 100,100,50 fill=none stroke=none name=b\n"
         "grad ref=b from=#ff0000 to=#0000ff dir=0\n")
hl, hr = px(H, 58, 100), px(H, 142, 100)
check("dir=0 横向：左红右蓝", hl[0] > hl[2] and hr[2] > hr[0], f"{hl} {hr}")

# 形状可以是组名
G = C + ("group name=g\nrect 40,40,50,50 fill=none stroke=none\n"
         "rect 110,110,50,50 fill=none stroke=none\nendgroup\n"
         "grad ref=g from=#ff0000 to=#ff0000\n")
check("ref 指向组：第一块有颜色", px(G, 60, 60) == (255, 0, 0), f"{px(G, 60, 60)}")
check("ref 指向组：第二块也有", px(G, 140, 140) == (255, 0, 0), f"{px(G, 140, 140)}")
check("ref 指向组：中间没有", px(G, 100, 100) == (255, 255, 255), f"{px(G, 100, 100)}")

# 老写法不能坏
OLD = C + "grad rect 20,20,160,160 from=#ff0000 to=#0000ff\n"
check("grad rect 老写法仍然可用", px(OLD, 100, 30)[0] > 200, f"{px(OLD, 100, 30)}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
