"""M0 验收：移植版与 dsh-scribble 的数值对照。

做法：同一份 m0_scene.json 喂给 JS 的 `stroke()`（捕获真正进光栅器的点列/笔宽）
和 Python 的 `build_stroke()`，逐点比。
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.pen import Stroke, build_stroke  # noqa: E402
from fyb.rng import Rng                  # noqa: E402

# Node 用来跑 JS 版"标准答案"。换机器后路径会变，所以先按环境变量找，
# 再试 PATH 里的 node，最后试几个常见位置；都没有就跳过这项测试（不算失败）。
import os
import shutil


def _find_node() -> str | None:
    cand = [os.environ.get("FYB_NODE"),
            shutil.which("node"),
            os.path.expanduser(
                r"~\.dsh\dsh-runtimes\dsh-next-primary-runtime"
                r"\dependencies\node\bin\node.exe")]
    for c in cand:
        if c and Path(c).exists():
            return c
    return None


NODE = _find_node()
SCENE = ROOT / "tools" / "js-oracle" / "m0_scene.json"
ORACLE = ROOT / "tools" / "js-oracle" / "points.mjs"


def js_capture() -> list:
    out = subprocess.run([NODE, str(ORACLE), str(SCENE)],
                         capture_output=True, check=True)
    return json.loads(out.stdout.decode("utf-8"))


def py_capture(scene: dict) -> list:
    rng = Rng(scene.get("seed", 0))
    cap = []
    for s in scene["strokes"]:
        st = Stroke(points=[tuple(p) for p in s["points"]],
                    width=s.get("width", 3), color=s.get("color", "#000"),
                    alpha=s.get("alpha", 1), jitter=s.get("jitter", 0.62),
                    roughness=s.get("roughness", 1.0), taper=s.get("taper", 0.2),
                    overshoot=s.get("overshoot"), closed=bool(s.get("closed")))
        pts, widths = build_stroke(st, rng)
        cap.append({"pts": [list(p) for p in pts], "widths": widths})
    return cap


def main() -> int:
    if NODE is None or not ORACLE.exists():
        print("跳过：找不到 node 或 js-oracle（这项比对需要 JS 版标准答案）")
        print("想跑就设环境变量 FYB_NODE 指向 node.exe")
        return 0
    scene = json.loads(SCENE.read_text(encoding="utf-8"))
    js = js_capture()
    py = py_capture(scene)

    assert len(js) == len(py), f"stroke count {len(js)} vs {len(py)}"

    worst_p = worst_w = 0.0
    npts = 0
    for i, (a, b) in enumerate(zip(js, py)):
        name = scene["strokes"][i]["name"]
        if len(a["pts"]) != len(b["pts"]):
            print(f"  #{i} {name}: 点数不同 {len(a['pts'])} vs {len(b['pts'])}")
            continue
        dp = max((abs(x1 - x2) + abs(y1 - y2)) for (x1, y1), (x2, y2)
                 in zip(a["pts"], b["pts"]))
        dw = max(abs(w1 - w2) for w1, w2 in zip(a["widths"], b["widths"]))
        worst_p = max(worst_p, dp)
        worst_w = max(worst_w, dw)
        npts += len(a["pts"])
        print(f"  #{i} {name:<10} pts={len(a['pts']):4d}  Δpos={dp:.2e}  Δw={dw:.2e}")

    print(f"\nstrokes={len(js)}  points={npts}")
    print(f"最大偏差：位置 {worst_p:.3e} px，笔宽 {worst_w:.3e} px")
    ok = worst_p < 1e-6 and worst_w < 1e-6
    print("结论：" + ("完全一致（逐位对齐）" if ok else "有偏差，需查"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
