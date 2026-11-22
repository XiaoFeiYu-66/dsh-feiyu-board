"""把一张图片按颜色分层矢量化成场景（.fyb 文本）。

用途：参考图是"干净的数码插画/图标"时，硬照着画不划算——形状太多、
每一笔都要判断。这套流程换个思路：让机器按颜色分层、逐层抽轮廓，
再按"面积大的先画"叠起来。小的细节面积小、后画，自然压在上面。

限制（很重要）：
- 只适合**色块分明**的图（插画、图标、扁平风）。照片、渐变多的图会碎成上千块。
- 每个区域只取**外轮廓**，内部镂空靠"后画的小色块"盖出来，
  所以层序错了就会盖反（按面积从大到小排就是为了这个）。
- 不保留笔触和纹理，产出是纯色块——"简化"，不是复刻。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

from .trace import simplify, trace_contour

# 小于这么多像素的区域当噪声丢掉
MIN_AREA = 380


def _box_sum(m: np.ndarray, win: int) -> np.ndarray:
    """滑动窗口求和（积分图），每个像素 O(1)。"""
    pad = win // 2
    p = np.pad(m.astype(np.float32), pad, mode="edge")
    ii = np.cumsum(np.cumsum(p, axis=0), axis=1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    h, w = m.shape
    return (ii[win:win + h, win:win + w] - ii[0:h, win:win + w]
            - ii[win:win + h, 0:w] + ii[0:h, 0:w])


def clean_labels(labels: np.ndarray, n_colors: int, win: int = 7) -> np.ndarray:
    """在"颜色标签"上做多数表决，消掉量化后的麻点。

    抗锯齿会在色与色之间留下过渡带，量化后变成一堆孤立的小色块。
    按颜色逐块滤波治不了（会把整块吃掉），在标签图上一次表决才干净。
    """
    counts = np.stack([_box_sum((labels == i).astype(np.float32), win)
                       for i in range(n_colors)])
    return counts.argmax(axis=0).astype(np.uint8)


def _components(mask: np.ndarray, min_area: int):
    """四连通分块，返回 [(面积, 子掩码), …]，按面积从大到小。"""
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
            if len(pix) < min_area:
                continue
            sub = np.zeros_like(mask)
            for y, x in pix:
                sub[y, x] = True
            out.append((len(pix), sub))
    out.sort(key=lambda t: -t[0])
    return out


def vectorize(image: str | Path, colors: int = 24, blur: float = 1.0,
              eps: float = 1.8, height: int = 1200, min_area: int = MIN_AREA,
              win: int = 7, title: str = "") -> tuple[str, dict]:
    """返回 (场景文本, 统计)。不写文件，调用方决定写哪。"""
    im = Image.open(str(image)).convert("RGB")
    # 量化前先轻糊：抗锯齿留的过渡带不糊掉，会量化出一堆细碎中间色
    if blur > 0:
        im = im.filter(ImageFilter.GaussianBlur(blur))
    iw, ih = im.size
    scale = height / ih
    cw = int(round(iw * scale))

    # OCTREE 而不是 MEDIANCUT：后者在"大面积白 + 少量肤色"这类图上
    # 会把肤色也量化成白的（人物的脸就发灰了）。
    q = im.quantize(colors=colors, method=Image.FASTOCTREE)
    labels = clean_labels(np.asarray(q).astype(np.uint8), colors, win=win)
    palette = q.getpalette()[:colors * 3]
    pal = [tuple(palette[i * 3:i * 3 + 3]) for i in range(colors)]

    regions = []
    for idx, color in enumerate(pal):
        for area, sub in _components(labels == idx, min_area):
            ys, xs = np.nonzero(sub)
            # 铺满整张画布的那块就是背景：不画，交给 bg
            if (xs.min() <= 2 and xs.max() >= iw - 3
                    and ys.min() <= 2 and ys.max() >= ih - 3):
                continue
            c = simplify(trace_contour(sub), eps, closed=True)
            if len(c) >= 3:
                regions.append((area, color, c))
    regions.sort(key=lambda t: -t[0])

    lines = [
        "canvas %dx%d" % (cw, height),
        "bg #FFFFFF",
        "",
        "# 由 fyb posterize 生成：按颜色分层 + 逐块抽轮廓。",
        "# 源图：%s　颜色 %d　模糊 %.1f　容差 %.1f" % (Path(image).name, colors, blur, eps),
        "# 色块 %d 个。要改风格就调颜色数和容差，别手改坐标。" % len(regions),
        "hand preset=clean seed=7",
        "",
    ]
    for area, color, pts in regions:
        path = " ".join("%d,%d" % (round(x * scale), round(y * scale)) for x, y in pts)
        lines.append("curve [%s] fill=#%02X%02X%02X stroke=none closed"
                     % (path, color[0], color[1], color[2]))
    lines.append("")
    if title:
        lines.append('text 60,%d "%s" 24 align=left color=#8A8FA8 hand=0.3'
                     % (height - 40, title))
        lines.append("")
    stats = {"width": cw, "height": height, "colors": colors,
             "regions": len(regions), "points": sum(len(c) for _, _, c in regions),
             # 最大一块的面积：噪点会把大块打散，这个数能直接反映"去噪有没有用"
             "max_area": max((a for a, _, _ in regions), default=0)}
    return "\n".join(lines), stats
