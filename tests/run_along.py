"""嵌套 along 的回归测试。

要点：内层 along 的 ref 路径写在**外层模板的局部坐标**里，
外层把模板摆到哪儿，内层就跟着摆到哪儿。
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


def px(src, x, y):
    r = compile_text(src)
    assert r.ok, [(e.code, e.line) for e in r.errors]
    cv = render(r.scene, scale=1)
    c = cv.img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


C = "canvas 400x200\nbg #ffffff\n"

# 外层沿横线摆 3 片"叶"，每片叶里再沿竖线摆 3 个点
NESTED = (C +
          "curve [40,100 360,100] fill=none stroke=none name=stem\n"
          "group name=叶\n"
          "  ellipse 0,0,26,12 fill=#88cc44\n"
          "  curve [0,-14 0,14] fill=none stroke=none name=脉\n"
          "  along ref=脉 group=点 count=3 rot=0\n"
          "endgroup\n"
          "group name=点\n"
          "  circle 0,0,3 fill=#004400\n"
          "endgroup\n"
          "along ref=stem group=叶 count=3\n")

# 外层 placement: t = (0.5)/3, (1.5)/3, (2.5)/3 → x = 40 + 320*t
xs = [40 + 320 * (i + 0.5) / 3 for i in range(3)]

# 每个叶片中心附近都该有内层的深色点（在叶片内部，y=100 附近）
for n, x in enumerate(xs):
    hit = any(px(NESTED, int(x), y)[1] < 120 for y in range(88, 113))
    check(f"第 {n + 1} 片叶里画出了内层点", hit, f"x={x:.0f}")

# 叶子外侧不该有内层点
outside = px(NESTED, int(xs[0]), 40)
check("叶子外面没有内层点", outside[1] > 200, f"{outside}")

# 对照组：把内层 along 删掉，那些点就不该有
FLAT = (C +
        "curve [40,100 360,100] fill=none stroke=none name=stem\n"
        "group name=叶\n"
        "  ellipse 0,0,26,12 fill=#88cc44\n"
        "endgroup\n"
        "along ref=stem group=叶 count=3\n")
no_dots = all(px(FLAT, int(x), y)[1] > 120 for x in xs for y in range(88, 113))
check("没有内层 along 时不该有点", no_dots)

# 环检测：组里套自己，要报错而不是死循环
CYCLE = (C + "group name=a\ncircle 0,0,5 fill=#333\n"
              "along ref=p group=a count=2\nendgroup\n"
              "curve [0,0 100,0] fill=none stroke=none name=p\n"
              "along ref=p group=a count=2\n")
r = compile_text(CYCLE)
check("along 自环会报错", not r.ok, f"{[(e.code, e.line) for e in r.errors]}")

# ── use 复制"含 along 的模板组" ──────────────────────────────
# 两处以前都是静默错误：
#   1. 模板里的图元是 invisible，复制出来还带着 invisible → 整个 use 什么都不画；
#   2. along 没有几何可变换，复制出来的 along 仍然画在原来的位置。
USE_SRC = ("canvas 400x300\nbg #ffffff\n" +
           "curve [0,-14 0,14] fill=none stroke=none name=脉\n"
           "group name=小脉 template=1\n"
           "  circle 0,0,4 fill=#004400\n"
           "endgroup\n"
           "group name=叶 template=1\n"
           "  ellipse 0,0,40,26 fill=#88cc44\n"
           "  along ref=脉 group=小脉 count=3 rot=0\n"
           "endgroup\n"
           "use 叶 at=[200,150]\n")


def dark_box(src):
    r = compile_text(src)
    assert r.ok, [(e.code, e.line) for e in r.errors]
    cv = render(r.scene, scale=1)
    im = cv.img
    hits = []
    for y in range(im.height()):
        for x in range(im.width()):
            c = im.pixelColor(x, y)
            if c.green() < 130 and c.red() < 130:
                hits.append((x, y))
    if not hits:
        return None
    return (min(h[0] for h in hits), max(h[0] for h in hits),
            min(h[1] for h in hits), max(h[1] for h in hits))


box = dark_box(USE_SRC)
check("use 模板组：内容画出来了", box is not None, "什么都没画")
if box:
    cx = (box[0] + box[2 - 1]) / 2 if False else (box[0] + box[1]) / 2
    cy = (box[2] + box[3]) / 2
    check("use 模板组：落在 at 指定的位置", abs(cx - 200) < 12 and abs(cy - 150) < 16,
          f"中心 ({cx:.0f},{cy:.0f})，期望 (200,150)")

# use 带旋转：点应该跟着转
ROT_SRC = USE_SRC.replace("use 叶 at=[200,150]", "use 叶 at=[200,150] rot=90")
b2 = dark_box(ROT_SRC)
check("use 带 rot：仍然画在 at 附近", b2 is not None and abs((b2[0] + b2[1]) / 2 - 200) < 16,
      f"{b2}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
