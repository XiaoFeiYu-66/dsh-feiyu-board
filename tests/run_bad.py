"""M1 验收：坏输入必须一次报全，且带行号/列号/错误码。

每个用例是一个 (名字, 源码, 期望 [(错误码, 行)])。
跑法：python tests/run_bad.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text  # noqa: E402
from fyb.errors import format_all   # noqa: E402

CANVAS = "canvas 1920x1080\n"

CASES = [
    ("E001 未知命令", CANVAS + "inl [1,2 3,4]\n", [("E001", 2)]),
    ("E002 参数个数", CANVAS + "circle 100,100\n", [("E002", 2)]),
    ("E003 颜色", CANVAS + "circle 100,100,50 fill=#GGG\n", [("E003", 2)]),
    ("E004 名字重复",
     CANVAS + "circle 100,100,50 fill=#111 name=body\ncircle 200,100,30 fill=#222 name=body\n",
     [("E004", 3)]),
    ("E006 组没配平", CANVAS + "group at=[10,10]\ncircle 100,100,50 fill=#111\n",
     [("E006", 2)]),
    ("E006 endgroup 多", CANVAS + "endgroup\n", [("E006", 2)]),
    ("E007 半径越界", CANVAS + "circle 100,100,-5 fill=#111\n", [("E007", 2)]),
    ("E007 笔宽越界", CANVAS + "ink [0,0 10,10] w=999\n", [("E007", 2)]),
    ("E008 缺 canvas", "bg #ffffff\ncircle 1,1,1 fill=#000\n", [("E008", 1)]),
    ("E009 闭合点不足", CANVAS + "curve [10,10 20,20] closed fill=#111\n", [("E009", 2)]),
    ("E010 续行悬空", CANVAS + "circle 100,100,50 fill=#111 \\\n", [("E010", 2)]),
    ("E011 未知属性", CANVAS + "circle 100,100,50 fill=#111 glow=yes\n",
     [("E011", 2)]),
    ("E012 数字", CANVAS + "rect 10,20,30,fourty fill=#111\n", [("E012", 2)]),
    ("E013 属性没值", CANVAS + "circle 100,100,50 fill=\n", [("E013", 2)]),
    ("E014 canvas 两次", CANVAS + "canvas 800x600\n", [("E014", 2)]),
    ("E015 属性写两遍",
     CANVAS + "circle 100,100,50 fill=#111 fill=#222\n", [("E015", 2)]),
    ("多个错误一次报全",
     CANVAS + "circle 100,100,50 fill=#GGG\ninl [1,2]\nrect 1,2,3,四\n",
     [("E003", 2), ("E001", 3), ("E012", 4)]),
]


def main() -> int:
    bad = 0
    for name, src, expect in CASES:
        res = compile_text(src)
        if expect is None:
            continue
        got = [(e.code, e.line) for e in res.errors]
        ok = got == expect
        cols = all(e.col >= 1 for e in res.errors)
        mark = "PASS" if ok and cols else "FAIL"
        if not (ok and cols):
            bad += 1
        print(f"[{mark}] {name:<18} 期望 {expect}  收到 {got}"
              + ("" if cols else "  (列号缺失)"))
        if not ok:
            print(format_all(res.errors, src, "<case>"))
    print(f"\n{len(CASES) - bad}/{len(CASES)} 通过")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
