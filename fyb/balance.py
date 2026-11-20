"""构图体检：把"画面空不空、重不重心"变成可量的数字。

用途：我判断不了"这张画是不是太空"，但可以量：
把画面切成 N×M 格，数每格里"有墨"的像素占比。
于是"右上角几乎是空的"从感觉变成 2%。

三件事：
1. 每格覆盖率（0~1）
2. 重心位置（笔画都挤在哪儿）
3. 四边/四角是否空着
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PySide6.QtGui import QImage


def image_to_array(img: QImage) -> np.ndarray:
    """QImage → (h, w, 3) uint8。

    必须 **拷贝**：`np.frombuffer(constBits())` 只是共享 QImage 的内存，
    函数返回后 QImage 一析构，数组就指着释放过的内存 —— 读出来是垃圾，
    有时候直接崩（实测把覆盖率算成 100%，还会静默退出）。
    """
    img = img.convertToFormat(QImage.Format_RGB888)
    w, h = img.width(), img.height()
    line = img.bytesPerLine()
    raw = np.frombuffer(img.constBits(), dtype=np.uint8, count=h * line).copy()
    return raw.reshape(h, line)[:, : w * 3].reshape(h, w, 3)


@dataclass
class Balance:
    cols: int
    rows: int
    grid: list[list[float]]      # 0~1 覆盖率
    coverage: float              # 全画布覆盖率
    centroid: tuple[float, float]  # 重心（0~1 相对坐标）
    empty_cells: list[tuple[int, int]]
    notes: list[str]


def analyze(img: QImage, cols: int = 4, rows: int = 3,
            bg: tuple[int, int, int] = (255, 255, 255),
            tol: int = 10) -> Balance:
    """量一张图：每格墨的占比 + 重心 + 空角。"""
    a = image_to_array(img).astype(np.int16)
    h, w, _ = a.shape
    diff = np.abs(a - np.array(bg)).max(axis=2)
    ink = diff > tol                       # 和背景差得够多就算"有墨"

    grid = []
    for r in range(rows):
        y0, y1 = int(h * r / rows), int(h * (r + 1) / rows)
        row = []
        for c in range(cols):
            x0, x1 = int(w * c / cols), int(w * (c + 1) / cols)
            cell = ink[y0:y1, x0:x1]
            row.append(float(cell.mean()) if cell.size else 0.0)
        grid.append(row)

    total = float(ink.mean())
    ys, xs = np.nonzero(ink)
    if len(xs):
        cx = float(xs.mean()) / max(1, w - 1)
        cy = float(ys.mean()) / max(1, h - 1)
    else:
        cx = cy = 0.5

    empty = [(r, c) for r in range(rows) for c in range(cols)
             if grid[r][c] < 0.03]

    flat = [v for row in grid for v in row]
    notes: list[str] = []
    if total < 0.02:
        notes.append("整张几乎是空的（覆盖率 %.1f%%）" % (total * 100))
    else:
        if empty:
            if len(empty) <= 4:
                where = "、".join("行%d列%d" % (r + 1, c + 1) for r, c in empty)
                notes.append("%d/%d 格是空的：%s"
                             % (len(empty), rows * cols, where))
            else:
                # 空格太多就只报数量 + 集中在哪几列/行
                cols_hit = sorted({c + 1 for _, c in empty})
                rows_hit = sorted({r + 1 for r, _ in empty})
                tag = []
                if len(cols_hit) <= 2:
                    tag.append("集中在第 %s 列" % "、".join(map(str, cols_hit)))
                if len(rows_hit) <= 2:
                    tag.append("集中在第 %s 行" % "、".join(map(str, rows_hit)))
                notes.append("%d/%d 格是空的%s"
                             % (len(empty), rows * cols,
                                ("（%s）" % "，".join(tag)) if tag else ""))
        # "太满"只在**完全没有留白**时才说：满版构图（房间、风景）不该误报
        if total > 0.85 and min(flat) > 0.4:
            notes.append("压得太满（覆盖率 %.0f%%，每格都在 40%% 以上）"
                         % (total * 100))
        if abs(cx - 0.5) > 0.12 or abs(cy - 0.5) > 0.12:
            hx = "偏左" if cx < 0.5 else "偏右"
            vy = "偏上" if cy < 0.5 else "偏下"
            notes.append("重心%s%s（%.2f, %.2f）" % (hx, vy, cx, cy))
    return Balance(cols, rows, grid, total, (cx, cy), empty, notes)


def _cell_name(r: int, c: int, rows: int, cols: int) -> str:
    hor = ("左", "中", "右") if cols == 3 else (
        ("左", "中左", "中右", "右") if cols == 4 else
        tuple("列%d" % (i + 1) for i in range(cols)))
    ver = ("上", "中", "下") if rows == 3 else tuple("行%d" % (i + 1) for i in range(rows))
    return "%s%s" % (ver[r], hor[c] if c < len(hor) else str(c))


def format_grid(b: Balance) -> str:
    """把覆盖率画成一张文字表（一眼看出哪儿空）。"""
    lines = []
    head = "      " + "".join("列%-5d" % (c + 1) for c in range(b.cols))
    lines.append(head)
    for r in range(b.rows):
        cells = "".join("%5.0f%% " % (b.grid[r][c] * 100) for c in range(b.cols))
        lines.append("行%d  %s" % (r + 1, cells))
    return "\n".join(lines)


def _font(size: int):
    """找一个能写中文的字体；找不到就返回 None（退回英文标注）。"""
    from pathlib import Path as _P
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "NotoSansCJK-Regular.ttc"):
        p = _P("C:/Windows/Fonts") / name
        if p.exists():
            try:
                from PIL import ImageFont
                return ImageFont.truetype(str(p), size)
            except Exception:            # noqa: BLE001
                continue
    return None


def annotate(img: QImage, b: Balance, grid_kind: str = "thirds",
             panel: int = 300) -> "Image.Image":
    """生成一张"体检图"：原图 + 构图线 + 每格覆盖率 + 右侧结论。

    grid_kind: thirds（三分线）/ golden（黄金分割）/ none
    """
    from PIL import Image, ImageDraw

    base = Image.fromarray(image_to_array(img))
    w, h = base.size
    canvas = Image.new("RGB", (w + panel, h), (250, 248, 244))
    canvas.paste(base, (0, 0))
    d = ImageDraw.Draw(canvas, "RGBA")
    f_big = _font(22)
    f_small = _font(17)

    # 构图线
    if grid_kind == "thirds":
        xs = [w / 3, w * 2 / 3]
        ys = [h / 3, h * 2 / 3]
    elif grid_kind == "golden":
        g = 0.381966
        xs = [w * g, w * (1 - g)]
        ys = [h * g, h * (1 - g)]
    else:
        xs, ys = [], []
    for x in xs:
        d.line([(x, 0), (x, h)], fill=(255, 90, 60, 130), width=2)
    for y in ys:
        d.line([(0, y), (w, y)], fill=(255, 90, 60, 130), width=2)

    # 每格覆盖率
    for r in range(b.rows):
        for c in range(b.cols):
            x0, x1 = w * c / b.cols, w * (c + 1) / b.cols
            y0, y1 = h * r / b.rows, h * (r + 1) / b.rows
            d.rectangle([x0, y0, x1, y1], outline=(90, 90, 90, 70))
            pct = b.grid[r][c] * 100
            col = (200, 60, 40, 255) if pct < 3 else (60, 60, 60, 220)
            txt = "%.0f%%" % pct
            d.text((x0 + 6, y0 + 4), txt, font=f_small, fill=col)

    # 右栏结论
    if f_big:
        d.text((w + 14, 14), "构图体检", font=f_big, fill=(40, 40, 40))
    d.text((w + 14, 52), "coverage %.1f%%" % (b.coverage * 100),
           font=f_small, fill=(60, 60, 60))
    d.text((w + 14, 76), "center (%.2f, %.2f)" % b.centroid,
           font=f_small, fill=(60, 60, 60))
    y = 110
    if not b.notes:
        d.text((w + 14, y), "no issues found" if not f_big else "没发现明显问题",
               font=f_small, fill=(40, 120, 60))
    else:
        for n in b.notes[:9]:
            d.text((w + 14, y), ("- " + n) if f_big else ("- " + n),
                   font=f_small, fill=(180, 60, 40))
            y += 26
    return canvas
