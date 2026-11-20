"""let / def 的回归测试。跑法：python tests/run_macro.py"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text          # noqa: E402

C = "canvas 700x400\nbg #f6efe2\n"
fails: list[str] = []


def case(name, src, *, ok=True, codes=(), prims=None):
    r = compile_text(src)
    got = [e.code for e in r.errors]
    bad = []
    if r.ok != ok:
        bad.append(f"ok={r.ok}")
    for c in codes:
        if c not in got:
            bad.append(f"缺 {c}（实得 {got}）")
    if prims is not None and r.scene is not None and len(r.scene.prims) != prims:
        bad.append(f"图元 {len(r.scene.prims)} != {prims}")
    if bad:
        fails.append(f"{name}: {'; '.join(bad)}")
        print(f"FAIL {name}  {bad}")
    else:
        print(f"ok   {name}")


# ── 变量 ────────────────────────────────────────────
case("变量当颜色", C + "let 主 = #C0392B\ncircle 200,200,100 fill=$主\n", prims=1)
case("变量算数字", C + "let r = 100\nlet h = $r * 0.5\ncircle 200,200,$h fill=#C0392B\n",
     prims=1)
case("变量没定义只报一次", C + "circle 100,100,50 fill=$没这个\n", ok=False, codes=("E017",))
case("变量可以互相引用", C + "let a = #112233\nlet b = $a\ncircle 1,1,2 fill=$b\n", prims=1)

# ── 宏 ──────────────────────────────────────────────
case("宏位置参数", C + """def 孔 (x, y, r)
  circle $x,$y,$r fill=#A8130A
enddef
孔 100,100,5
孔 200,150,7
""", prims=2)

case("宏里用全局变量", C + """let 暗 = #A8130A
def 孔 (x, y)
  circle $x,$y,6 fill=$暗
enddef
孔 100,100
""", prims=1)

case("宏套宏", C + """def 点 (x, y)
  circle $x,$y,4 fill=#111111
enddef
def 一对 (x, y)
  点 $x,$y
  点 $x,$y
enddef
一对 300,300
""", prims=2)

case("宏能收点列", C + """def 斑 (pts)
  curve $pts fill=#C0140A alpha=0.3
enddef
斑 [10,10 50,10 50,50]
""", prims=1)

# ── 宏的错，要报在调用点 ─────────────────────────────
r = compile_text(C + """def 坏 (x)
  circle $x,0,10 fill=zzz
enddef
坏 5
""")
if r.ok or not r.errors or r.errors[0].line != 6:
    fails.append(f"行号指向调用点: {[(e.code, e.line) for e in r.errors]}")
    print("FAIL 行号指向调用点")
else:
    print("ok   行号指向调用点（第 6 行）")

case("参数个数不对", C + """def 点 (x, y)
  circle $x,$y,4 fill=#111
enddef
点 5
""", ok=False, codes=("E014",))
case("宏调自己会停", C + """def 圈 (n)
  圈 $n
enddef
圈 1
""", ok=False, codes=("E016",))
case("宏名撞命令", C + "def circle (x)\nbg #fff\nenddef\n", ok=False, codes=("E014",))
case("def 没 enddef", C + "def 点 (x)\ncircle $x,0,4 fill=#111\n", ok=False,
     codes=("E016",))
case("enddef 多了", C + "enddef\n", ok=False, codes=("E016",))
case("$$ 转义", C + 'let s = "价 $$5"\ntext 10,10 $s 30 align=left color=#111\n',
     prims=1)

# ── 真正要证的那件事：改一处，全局跟着变 ────────────────
# 气孔的颜色定义在 scenes/lib/parts.fyb 里，场景只用一行就能覆盖它。
scene_path = ROOT / "scenes" / "orange2.fyb"
scene_text = scene_path.read_text(encoding="utf-8")
base = compile_text(scene_text, scene_path.parent)
before = sum(1 for p in base.scene.prims if p.fill == "#a8130a") if base.scene else 0

swapped = compile_text(scene_text + "\nlet 孔色 = #0055FF\n", scene_path.parent)
after = sum(1 for p in swapped.scene.prims if p.fill == "#0055ff") if swapped.scene else 0
left = sum(1 for p in swapped.scene.prims if p.fill == "#a8130a") if swapped.scene else -1

if before == 16 and after == before and left == 0:
    print(f"ok   改一处颜色：{before} 个气孔一次全变（旧色残留 {left}）")
else:
    fails.append(f"改一处颜色: before={before} after={after} left={left}")
    print(f"FAIL 改一处颜色: before={before} after={after} left={left}")

# ── include：跨文件复用 ─────────────────────────────
from fyb.compiler import compile_file         # noqa: E402

tmp = ROOT / "tests" / "_tmp_include"
tmp.mkdir(exist_ok=True)
(tmp / "lib.fyb").write_text(
    "let 库里颜色 = #6FB92F\n"
    "def 库点 (x, y)\n  circle $x,$y,5 fill=$库里颜色\nenddef\n", encoding="utf-8")
(tmp / "a.fyb").write_text(
    'canvas 300x300\nbg #ffffff\ninclude "lib.fyb"\n库点 10,10\n库点 20,20\n',
    encoding="utf-8")
(tmp / "loop1.fyb").write_text('include "loop2.fyb"\n', encoding="utf-8")
(tmp / "loop2.fyb").write_text('include "loop1.fyb"\n', encoding="utf-8")
(tmp / "miss.fyb").write_text('include "nope.fyb"\n', encoding="utf-8")

r = compile_file(str(tmp / "a.fyb"))
if r.ok and len(r.scene.prims) == 2 and r.scene.prims[0].fill == "#6fb92f":
    print("ok   include 能带进变量和宏")
else:
    fails.append(f"include: ok={r.ok} {[(e.code, e.line) for e in r.errors]}")
    print(f"FAIL include  {[(e.code, e.line) for e in r.errors]}")

for name, code in (("loop1.fyb", "E018"), ("miss.fyb", "E018")):
    r = compile_file(str(tmp / name))
    got = [e.code for e in r.errors]
    if code in got:
        print(f"ok   include 报 {code}（{name}）")
    else:
        fails.append(f"include {name}: {got}")
        print(f"FAIL include {name}: {got}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
