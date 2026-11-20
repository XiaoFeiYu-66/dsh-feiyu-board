"""从参考图生成鲸鱼图标的场景。

为什么要生成：这个图标是"一个实心色块 + 几个白色镂空"，
外形必须**量**出来（手算 70 多个点是徒劳），镂空也要按图里的位置来。
所以这里把参考图当真值：
  1. 二值化 → 蓝色块
  2. 从四边泛洪，标出"外面"
  3. 内部白色 = 白 & 非外面 → 那就是三个镂空
  4. 各自抽轮廓、简化、按比例缩到画布
产出的 .fyb 是**数据驱动**的，改参考图重跑即可。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.trace import simplify, trace_contour   # noqa: E402

REF = sys.argv[1] if len(sys.argv) > 1 else None
OUT = ROOT / "scenes" / "whale-icon.fyb"
H = 900          # 画布高
EPS = 4.5        # 简化容差（参考图像素）；太小会把像素台阶留着
MIN_AREA = 300   # 小于这个面积的白区当噪声


def load(path: str):
    im = Image.open(path).convert("RGB")
    a = np.asarray(im).astype(np.int16)
    r, g, b = a[:, :, 0], a[:, :, 1], a[:, :, 2]
    # 蓝色：偏蓝且不太亮（白底的三个通道都接近 255）
    blue = (b > 150) & (b.astype(int) - r > 25) & (b > g)
    return blue


def outside_of(mask: np.ndarray) -> np.ndarray:
    """从四边把"连通到边界"的空白标出来。"""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    stack = []
    for x in range(w):
        for y in (0, h - 1):
            if not mask[y, x]:
                stack.append((y, x))
    for y in range(h):
        for x in (0, w - 1):
            if not mask[y, x]:
                stack.append((y, x))
    for y, x in stack:
        seen[y, x] = True
    while stack:
        y, x = stack.pop()
        for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            yy, xx = y + dy, x + dx
            if 0 <= yy < h and 0 <= xx < w and not seen[yy, xx] and not mask[yy, xx]:
                seen[yy, xx] = True
                stack.append((yy, xx))
    return seen


def components(mask: np.ndarray):
    """四连通分块，返回 [(面积, 子掩码), …]。"""
    h, w = mask.shape
    seen = np.zeros_like(mask, bool)
    out = []
    for y0 in range(h):
        for x0 in range(w):
            if not mask[y0, x0] or seen[y0, x0]:
                continue
            stack = [(y0, x0)]
            seen[y0, x0] = True
            pix = []
            while stack:
                y, x = stack.pop()
                pix.append((y, x))
                for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    yy, xx = y + dy, x + dx
                    if 0 <= yy < h and 0 <= xx < w and mask[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True
                        stack.append((yy, xx))
            if len(pix) < MIN_AREA:
                continue
            sub = np.zeros_like(mask)
            for y, x in pix:
                sub[y, x] = True
            out.append((len(pix), sub))
    out.sort(key=lambda t: -t[0])
    return out


def main() -> int:
    if not REF or not Path(REF).exists():
        print("用法: python tools/whale_icon.py <参考图>", file=sys.stderr)
        return 1
    blue = load(REF)
    ih, iw = blue.shape
    scale = H / ih
    cw = int(round(iw * scale))

    # 外形：直接走蓝色块自己的轮廓。
    # （反过来走 ~blue 会从"图最左上的空白"起跳，只得到画布边框的 4 个角）
    body = trace_contour(blue)
    body = simplify(body, EPS, closed=True)

    # 内部白洞
    outside = outside_of(blue)
    inner_white = (~blue) & (~outside)
    holes = []
    for area, sub in components(inner_white):
        c = simplify(trace_contour(sub), EPS, closed=True)
        if len(c) >= 3:
            holes.append((area, c))

    def fmt(pts):
        return " ".join("%d,%d" % (round(x * scale), round(y * scale)) for x, y in pts)

    lines = [
        "canvas %dx%d" % (cw, H),
        "bg #FFFFFF",
        "",
        "# 由 tools/whale_icon.py 从参考图生成：外形和镂空都是量出来的，不是估的。",
        "# 重跑：python tools/whale_icon.py <参考图>",
        "hand preset=brush seed=12",
        "",
        "let 蓝 = #5B78EE",
        "",
        "# ── 身体（外轮廓）──────────────────────────────",
        "curve [%s] fill=$蓝 stroke=none closed name=身" % fmt(body),
    ]
    names = ["肚", "孔", "眼"]
    for i, (area, c) in enumerate(holes[:3]):
        nm = names[i] if i < len(names) else "洞%d" % i
        lines += [
            "",
            "# ── 内部白洞 %s（面积 %d）─────────────────────" % (nm, area),
            "curve [%s] fill=#FFFFFF stroke=none closed name=%s" % (fmt(c), nm),
        ]
    lines += ["", 'text 80,%d "鲸鱼 · 照参考图" 26 align=left color=#8A8FA8 hand=0.3'
              % (H - 50), ""]
    OUT.write_text("\n".join(lines), encoding="utf-8")
    print("%s  %dx%d  外形 %d 点  白洞 %d 个（%s）"
          % (OUT.name, cw, H, len(body), len(holes),
             ", ".join(str(len(c)) for _, c in holes[:3])))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
