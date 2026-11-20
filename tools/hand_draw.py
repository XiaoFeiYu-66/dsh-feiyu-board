"""把 trace 出来的点列重新画成一张画（临摹 → 取舍 → 上笔）。

fyb trace 只负责"给坐标"，这一步才是画：
- 只留真正属于这只手的两条线（丢掉邻手和下一行的碎片）
- 换成我的笔（铅笔预设 + 纸纹）
- 加体积：手掌下缘的接触阴影、掌心暗面、指节短纹

用法：python tools/hand_draw.py
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "scenes" / "hand-skel.fyb"
OUT = ROOT / "scenes" / "hand-drawn.fyb"

KEEP = [0, 2]          # 0 = 手的外轮廓；2 = 掌心那道纹
DX, DY = -60, -14      # 平移，把手摆到画面中间
CANVAS = (1000, 1040)


def parse_curves(text: str) -> list[list[tuple[float, float]]]:
    out = []
    for m in re.finditer(r"curve \[([^\]]+)\]", text):
        pts = []
        for tok in m.group(1).split():
            x, y = tok.split(",")
            pts.append((float(x), float(y)))
        out.append(pts)
    return out


def fmt(pts) -> str:
    return " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)


def main() -> int:
    curves = parse_curves(SRC.read_text(encoding="utf-8"))
    chosen = []
    for idx in KEEP:
        if idx < len(curves):
            chosen.append([(x + DX, y + DY) for x, y in curves[idx]])

    outline, crease = chosen[0], chosen[1]
    # 两端都落在手腕上；把它们往下拉出画布外 ——
    # 闭合时那条"封口线"就跑到画面外了，否则腕口会出现一道横线。
    outline[0] = (outline[0][0], CANVAS[1] + 90)
    outline[-1] = (outline[-1][0], CANVAS[1] + 90)
    xs = [p[0] for p in outline]
    ys = [p[1] for p in outline]
    cx = (min(xs) + max(xs)) / 2

    # 掌心大概在轮廓下半部分的中间；阴影贴着掌底
    palm_bottom = max(ys) - 120

    body = f"""canvas {CANVAS[0]}x{CANVAS[1]}
bg #F3EDE0

# 由 tools/hand_draw.py 生成：点列来自 `fyb trace`（骨架模式，阈值 0.86），
# 取舍和笔法在这里定。参考图 refs/hands.jpg 左上那只。
#
# 关键一步：轮廓的两端都在手腕上，所以可以 **闭合** ——
# 闭合之后它就不是一条线，而是一个"手形"，能拿来做剪裁和投影。
hand preset=pencil seed=88

let 铅 = #3B342B
let 淡 = #8B8070
let 纸 = #F3EDE0

# 1) 手形（只当几何，不画）
curve [{fmt(outline)}] fill=none stroke=none closed name=hand

# 2) 压在纸上的影子：偏移小、模糊中等 —— 手是贴着纸的，不是浮着的
shadow ref=hand dx=8 dy=14 blur=24 alpha=0.20 color=#8A7355

# 3) 掌心的暗面：multiply 压，边界靠渐变淡出
blend multiply
  clip hand
    grad circle {cx - 60:.0f},{palm_bottom - 60:.0f},340 from=#C9B79A4D to=#C9B79A00
  endclip
endblend

# 4) 轮廓：一笔描下来
curve [{fmt(outline)}] w=7 stroke=$铅 tex=paper tex_scale=0.45 \\
      jitter=0.45 taper=0 closed

# 5) 掌心纹：trace 出来的那条只有 13 个点、是一段竖着的碎线，不能用。
#    这两条按参考图量。**必须 clip 到手形里**，否则线会跑出掌心
#    （第一次没裁，两条纹直接横穿到手掌外面去了）。
clip hand
  curve [268,600 360,646 470,672 600,668] w=5 stroke=$淡 \\
        tex=paper tex_scale=0.4 alpha=0.8 jitter=0.6 taper=0.45
  curve [300,722 400,766 520,792] w=4 stroke=$淡 \\
        tex=paper tex_scale=0.4 alpha=0.65 jitter=0.6 taper=0.5
endclip

text 52,986 "手 · 临摹后重画" 24 align=left color=$淡 hand=0.4
"""
    OUT.write_text(body, encoding="utf-8")
    print(f"wrote {OUT}  （轮廓 {len(outline)} 点，掌纹 {len(crease)} 点）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
