"""属性别名的回归测试。

背景：同一个概念在不同命令上名字不一样（形状族 `stroke`/`width`，
笔族 `color`/`w`），模型照着上一条命令泛化就会吃 E011。
现在解析期按每个命令的 Spec 自动推导别名，这条测试守住它。

注意：别名只在**该命令本来就没有这个名字**时才生效，
所以 `curve` 同时有 `w` 和 `width` 时两者都算正式名，不算别名。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text                      # noqa: E402
from fyb.parser import VERBS, aliases_for                  # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


H = "canvas 300x300\nbg #fff\n"

# 以前会 E011 的写法，现在都该过
PASS_CASES = {
    "ellipse 用 w=": H + "ellipse 150,150,80,50 stroke=#333 w=5\n",
    "circle 用 w=": H + "circle 150,150,60 stroke=#333 w=6\n",
    "rect 用 w=": H + "rect 20,20,200,100 stroke=#333 w=4\n",
    "curve 用 color=": H + "curve [10,10 200,200] w=8 color=#333\n",
    "poly 用 color=": H + "poly [10,10 200,200 100,250] w=6 color=#333\n",
    "ink 用 width=": H + "ink [10,10 200,200] width=5 color=#333\n",
    "ink 用 stroke=": H + "ink [10,10 200,200] w=5 stroke=#333\n",
    "text 用 alpha=": H + 'text 20,20 "字" 30 color=#333 alpha=0.5\n',
    "hatch 用 width=": H + ("curve [10,10 200,100 120,240] closed fill=#eee name=x\n"
                            "hatch ref=x width=2 color=#333\n"),
    "hand 用 w=": H + "hand w=5\n",
}
for name, src in PASS_CASES.items():
    r = compile_text(src)
    check(name, r.ok, str([(e.code, e.line, e.message[:30]) for e in r.errors]))

# 正式名照旧可用
for name, src in {
    "ellipse 用 width=": H + "ellipse 150,150,80,50 stroke=#333 width=5\n",
    "ink 用 w=": H + "ink [10,10 200,200] w=5 color=#333\n",
}.items():
    check(name + "（正式名不受影响）", compile_text(src).ok)

# 真·未知属性仍然报 E011，而且提示里要带上可用别名
r = compile_text(H + "circle 100,100,50 fill=#111 glow=yes\n")
check("未知属性仍然拒", (not r.ok) and r.errors[0].code == "E011",
      str([(e.code, e.message[:40]) for e in r.errors]))
check("错误提示里列出别名", "别名" in r.errors[0].message, r.errors[0].message[:80])

# 别名撞车要算"写了两遍"，不能悄悄取后一个
r = compile_text(H + "ink [10,10 200,200] w=5 width=7 color=#333\n")
check("w= 和 width= 同时写算重复", (not r.ok) and r.errors[0].code == "E015",
      str([(e.code, e.message[:40]) for e in r.errors]))

# 别名表本身的形状：有 width 没 w 的命令，w 是别名；反之亦然
for verb, spec in VERBS.items():
    ks = set(spec.keys)
    al = aliases_for(spec.keys)
    if "width" in ks and "w" not in ks:
        check(f"{verb}: w 是 width 的别名", al.get("w") == "width", str(al))
    elif "w" in ks and "width" not in ks:
        check(f"{verb}: width 是 w 的别名", al.get("width") == "w", str(al))
    if "stroke" in ks and "color" not in ks:
        check(f"{verb}: color 是 stroke 的别名", al.get("color") == "stroke", str(al))
    elif "color" in ks and "stroke" not in ks:
        check(f"{verb}: stroke 是 color 的别名", al.get("stroke") == "color", str(al))

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
