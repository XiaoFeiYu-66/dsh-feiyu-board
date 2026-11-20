"""组透明的回归测试。

要点：group alpha 是**整组合成一次**，不是把每个子图元调透明——
组内两笔重叠的地方，不能叠出更深的颜色。嵌套组的 alpha 要逐层相乘，
而且内层仍然按"组"合成，不能退化成"逐个图元调 alpha"。
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


C = "canvas 200x200\nbg #ffffff\n"

# 两个圆重叠。组 alpha=0.5 时，重叠处应该和单块处**一样**（0.5 的黑）
ONE = C + ("group alpha=0.5\n"
           "circle 100,100,40 fill=#000000\n"
           "circle 130,100,40 fill=#000000\n"
           "endgroup\n")
solo = px(ONE, 70, 100)        # 只有第一个圆覆盖
overlap = px(ONE, 115, 100)    # 两个圆都覆盖
# 50% 的黑压在白纸上是 (127,127,127)，三通道和约 382
check("组透明：单块处是半透明的黑", abs(sum(solo) - 382) < 20, f"{solo}")
check("组透明：重叠处不再叠深", abs(sum(overlap) - sum(solo)) <= 6,
      f"solo={solo} overlap={overlap}")

# 对照：把 alpha 写在每个图元上，重叠处会更深 —— 证明这个测试有区分度
FLAT = C + ("circle 100,100,40 fill=#000000 alpha=0.5\n"
            "circle 130,100,40 fill=#000000 alpha=0.5\n")
flat_overlap = px(FLAT, 115, 100)
check("对照：逐个调 alpha 会叠深", sum(flat_overlap) < sum(overlap) - 20,
      f"flat={flat_overlap} group={overlap}")

# 嵌套：外层 0.5 × 内层 0.5 = 0.25
NEST = C + ("group alpha=0.5\n"
            "group alpha=0.5\n"
            "circle 100,100,40 fill=#000000\n"
            "endgroup\n"
            "endgroup\n")
inner = px(NEST, 100, 100)
check("嵌套组 alpha 相乘", abs(sum(inner) - 255 * 0.75 * 3) < 40,
      f"{inner}（期望接近 25% 黑）")

# alpha=1 的组不该开层，行为跟没写一样
PLAIN = C + "circle 100,100,40 fill=#000000\n"
WITH1 = C + "group alpha=1\ncircle 100,100,40 fill=#000000\nendgroup\n"
check("alpha=1 与不写等价", px(WITH1, 100, 100) == px(PLAIN, 100, 100),
      f"{px(WITH1, 100, 100)} vs {px(PLAIN, 100, 100)}")

# 组外的图元不受影响
OUT = C + ("group alpha=0.3\ncircle 60,60,30 fill=#000000\nendgroup\n"
           "circle 150,150,20 fill=#000000\n")
check("组外图元仍是实心", px(OUT, 150, 150) == (0, 0, 0), f"{px(OUT, 150, 150)}")
check("组内图元变淡", sum(px(OUT, 60, 60)) > 100, f"{px(OUT, 60, 60)}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
