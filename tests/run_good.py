"""M1 正例：能编过的场景必须真的编过，且结构对得上。

跑法：python tests/run_good.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_file, compile_text  # noqa: E402

CASES = []


def case(fn):
    CASES.append(fn)
    return fn


@case
def minimal():
    res = compile_text("canvas 800x600\nbg #102030\ncircle 400,300,100 fill=#ff0000\n")
    assert res.ok, res.errors
    s = res.scene
    assert (s.width, s.height) == (800, 600), s
    assert s.bg == "#102030"
    assert len(s.prims) == 1 and s.prims[0].kind == "circle"
    assert s.prims[0].rect[2] == 200, s.prims[0].rect


@case
def bom_prefix():
    """Windows 工具写的 BOM 不是语法错误。"""
    res = compile_text("\ufeffcanvas 800x600\nbg #102030\ncircle 1,1,1 fill=#ffffff\n")
    assert res.ok, res.errors


@case
def groups_transform():
    res = compile_text(
        "canvas 800x600\n"
        "group at=[100,100] scale=2\n"
        "  circle 10,10,5 fill=#ffffff\n"
        "endgroup\n")
    assert res.ok, res.errors
    x, y, w, h = res.scene.prims[0].rect
    assert abs(x - 110) < 1e-6 and abs(y - 110) < 1e-6, (x, y)
    assert abs(w - 20) < 1e-6, w


@case
def names_registered():
    res = compile_text(
        "canvas 800x600\n"
        "circle 1,1,5 fill=#fff name=eye\n"
        "group name=face at=[10,10]\n"
        "  circle 2,2,5 fill=#fff name=mouth\n"
        "endgroup\n")
    assert res.ok, res.errors
    assert res.scene.by_name("eye") is not None
    assert res.scene.by_name("mouth") is not None


@case
def night_scene():
    res = compile_file(str(ROOT / "scenes" / "night-m1.fyb"))
    assert res.ok, res.errors
    s = res.scene
    assert (s.width, s.height) == (1920, 1080)
    kinds = {}
    for p in s.prims:
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    assert kinds.get("ink", 0) >= 4, kinds
    assert kinds.get("text", 0) == 2, kinds
    inks = [p for p in s.prims if p.kind == "ink"]
    assert all(p.pen["wavelength"] > 0 for p in inks), inks[0].pen


@case
def hand_presets_and_text():
    res = compile_text(
        "canvas 800x400\n"
        "hand preset=pencil\n"
        "ink [10,10 200,60] w=4\n"
        "text 20,200 \"手写的字\" 40 hand=1\n")
    assert res.ok, res.errors
    ink = next(p for p in res.scene.prims if p.kind == "ink")
    txt = next(p for p in res.scene.prims if p.kind == "text")
    assert abs(ink.pen["jitter"] - 0.62) < 1e-9, ink.pen     # pencil 预设
    assert abs(txt.hand - 1.0) < 1e-9, txt.hand


def main() -> int:
    bad = 0
    for fn in CASES:
        try:
            fn()
            print(f"[PASS] {fn.__name__}")
        except AssertionError as ex:
            bad += 1
            print(f"[FAIL] {fn.__name__}: {ex}")
    print(f"\n{len(CASES) - bad}/{len(CASES)} 通过")
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
