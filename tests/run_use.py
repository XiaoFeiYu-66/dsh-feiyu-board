"""`use` 复用组的回归测试。

这里盯的是三个曾经"静默错"的地方：

1. 克隆品内部的引用（grad ref / clip / shadow ref / along 的路径）必须指向
   **自己这一份**，不能还指着原模板 —— 否则渐变、侧脉全画到原点去了。
2. `_clone_prim` 必须深拷 grad。浅拷的话所有克隆品共用一个 dict，
   一改引用就等于改了全家（五片叶子全指到第一片）。
3. along 克隆不能再叠一次 use 的矩阵。参考路径已经被克隆成新坐标了，
   再乘一遍位置正好翻倍（实测 dx 200 → 400）。
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


# ── 1. 引用重映射：两片叶子各有各的 grad ref ────────────────
LEAF = """canvas 400x400
bg #ffffff
group name=叶 template=1
  curve [0,0 -20,-30 0,-60 20,-30] fill=#7ab33c stroke=none closed name=形
  grad ref=形 from=#C2E06E to=#5E9B33 p0=[0,-58] p1=[0,2]
endgroup
use 叶 at=[100,300]
use 叶 at=[300,300]
"""
r = compile_text(LEAF)
check("use 模板：编译通过", r.ok, str([(e.code, e.line) for e in r.errors]))
if r.ok:
    # 模板自己的图元还留在场景里（只是 invisible），要只看**可见的**克隆
    grads = [p for p in r.scene.prims if p.kind == "grad" and not p.invisible]
    refs = [g.grad.get("ref") for g in grads]
    check("克隆的 grad 有两个", len(grads) == 2, str(len(grads)))
    check("两个克隆的 grad ref 互不相同", len(set(refs)) == 2, str(refs))
    check("克隆的 ref 不再指向模板名", all(x != "形" for x in refs), str(refs))

    # 每个 ref 的形状要落在各自的实例附近，而不是原点
    by_name = {p.name: p for p in r.scene.prims if p.name}
    boxes = []
    for x in refs:
        p = by_name.get(x)
        if p is None:
            boxes.append(None)
            continue
        xs = [q[0] for q in p.points]
        boxes.append((min(xs), max(xs)))
    ok = all(b is not None for b in boxes)
    check("ref 都能解析到实体", ok, str(boxes))
    if ok:
        check("第一个实例的形状在 x≈100", abs((boxes[0][0] + boxes[0][1]) / 2 - 100) < 30,
              str(boxes[0]))
        check("第二个实例的形状在 x≈300", abs((boxes[1][0] + boxes[1][1]) / 2 - 300) < 30,
              str(boxes[1]))

    # p0 / p1 也得跟着搬走（不搬的话渐变轴还留在模板原点，画出来是平色）
    if ok:
        g0 = grads[0].grad
        check("渐变轴跟着实例搬走", abs(g0["p0"][0] - 100) < 30, str(g0["p0"]))


# ── 2. 两片叶子都要真的有渐变（渲染层面）────────────────────
def colors_at(src, pts):
    r = compile_text(src)
    assert r.ok, [(e.code, e.line) for e in r.errors]
    cv = render(r.scene, scale=1)
    out = []
    for (x, y) in pts:
        c = cv.img.pixelColor(x, y)
        out.append((c.red(), c.green(), c.blue()))
    return out


pair = colors_at(LEAF, [(100, 262), (300, 262)])
check("两片叶子都有颜色（不是白的）", all(sum(c) < 700 for c in pair), str(pair))
check("两片叶子的颜色一致（同样的渐变）", pair[0] == pair[1], str(pair))

# 渐变轴 p0 在叶尖、p1 在叶基：叶尖浅、叶基深
top, bottom = colors_at(LEAF, [(100, 246), (100, 288)])
check("叶子内部有渐变（尖浅基深）", top[1] > bottom[1], f"尖{top} 基{bottom}")


# ── 3. 带 along 的模板：侧脉要落在每个实例上，且不能翻倍 ──────
VEIN = """canvas 500x400
bg #ffffff
group name=叶 template=1
  curve [0,0 -20,-30 0,-60 20,-30] fill=#9ACC55 stroke=none closed name=形
  curve [0,-8 0,-54] fill=none stroke=none name=脉路
  along ref=脉路 group=侧脉 count=3 rot=1
endgroup
group name=侧脉 template=1
  curve [0,0 -10,-18] w=3 stroke=#254A18
  curve [0,0 -10,18] w=3 stroke=#254A18
endgroup
use 叶 at=[120,300]
use 叶 at=[380,300]
"""
r2 = compile_text(VEIN)
check("带 along 的模板：编译通过", r2.ok, str([(c.code, c.line) for c in r2.errors]))
if r2.ok:
    al = [p for p in r2.scene.prims if p.kind == "along"]
    check("两个 along 克隆 + 模板本体（共 3 个）", len(al) == 3, str(len(al)))
    # 克隆不能带 mate：参考路径已经重映射成克隆自己的坐标了
    clones = [p for p in al if not p.invisible]
    check("克隆的 along 不带多余矩阵", all(p.mate is None for p in clones),
          str([p.mate for p in clones]))
    refs = [p.grad.get("ref") for p in clones]
    check("两个 along 指向不同的路径", len(set(refs)) == 2, str(refs))


def dark_near(src, x, y, half=40):
    r = compile_text(src)
    assert r.ok
    cv = render(r.scene, scale=1)
    for yy in range(max(0, y - half), min(cv.img.height(), y + half)):
        for xx in range(max(0, x - half), min(cv.img.width(), x + half)):
            c = cv.img.pixelColor(xx, yy)
            if c.green() < 110 and c.red() < 90:
                return True
    return False


check("第一个实例里有侧脉", dark_near(VEIN, 120, 270))
check("第二个实例里有侧脉", dark_near(VEIN, 380, 270))

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
