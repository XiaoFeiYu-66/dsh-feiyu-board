"""印章笔刷（along spacing / jitter）的回归测试。

判据用「数墨块」：
- 沿路径横着扫一行，统计"墨的连续段"个数 ≈ 印章枚数
- spacing 固定时，路径越长 → 段数越多（按长度定间距）
- jitter=0 时，路径两侧的带子里没有墨；jitter>0 时会有（散开）
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


HEAD = "canvas 900x300\nbg #FFFFFF\nhand preset=clean seed=4\n"
TIP = """group name=尖 template=1
  ellipse 0,0,7,7 fill=#000000
endgroup
"""


def scene(x2: int, spacing: int = 0, count: int = 5, jitter: float = 0,
          y: int = 150) -> str:
    parts = [HEAD, TIP]
    parts.append(f"curve [100,{y} {x2},{y}] fill=none stroke=none name=路\n")
    kw = f"spacing={spacing} " if spacing else f"count={count} "
    parts.append(f"along ref=路 group=尖 {kw}jitter={jitter} rot=0\n")
    return "".join(parts)


def ink_rows(src: str, y0: int, y1: int):
    """在 y0..y1 这个横带里，按列判断有没有墨。"""
    r = compile_text(src)
    assert r.ok, [(e.code, e.message) for e in r.errors]
    cv = render(r.scene, scale=1)
    cols = []
    for x in range(cv.img.width()):
        dark = False
        for y in range(y0, y1):
            c = cv.img.pixelColor(x, y)
            if c.red() < 120 and c.green() < 120 and c.blue() < 120:
                dark = True
                break
        cols.append(dark)
    return cols


def runs(cols) -> int:
    n, prev = 0, False
    for c in cols:
        if c and not prev:
            n += 1
        prev = c
    return n


# 1) spacing 决定枚数：路径 400px、间距 50 → 约 8 枚
n1 = runs(ink_rows(scene(500, spacing=50), 140, 160))
check("spacing=50 在 400px 上约 8 枚", 7 <= n1 <= 9, f"数到 {n1}")

# 2) 路径加倍 → 枚数也加倍（按长度而不是固定 count）
n2 = runs(ink_rows(scene(700, spacing=50), 140, 160))
check("路径拉到 600px：枚数跟着变多", n2 > n1 + 2, f"{n1} → {n2}")

# 3) spacing=0 时退回 count（老行为不受影响）
n3 = runs(ink_rows(scene(500, count=5), 140, 160))
check("不给 spacing 时 count=5 仍然生效", 4 <= n3 <= 6, f"数到 {n3}")

# 4) jitter=0：路径上下 12px 外的带子里没有墨
above0 = ink_rows(scene(500, spacing=50, jitter=0), 120, 138)
check("jitter=0：路径上方没有散落的墨", runs(above0) == 0, f"{runs(above0)} 段")

# 5) jitter=0.6：会有墨散到路径外
above = ink_rows(scene(500, spacing=50, jitter=0.6), 120, 138)
check("jitter=0.6：墨会散到路径外", runs(above) > 0, f"{runs(above)} 段")

# 6) 同一份场景两次渲染完全一致（抖动用的是散列种子）
a = ink_rows(scene(500, spacing=50, jitter=0.6), 140, 160)
b = ink_rows(scene(500, spacing=50, jitter=0.6), 140, 160)
check("同一场景两次渲染结果一致", a == b)

# 7) 参数校验
for bad, why in (("spacing=-1", "负数"), ("jitter=2", "超范围")):
    r = compile_text(scene(500, spacing=0) + f"along ref=路 group=尖 {bad}\n")
    check(f"along {bad}（{why}）被拒", not r.ok,
          str([(e.code, e.message[:36]) for e in r.errors]))

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
