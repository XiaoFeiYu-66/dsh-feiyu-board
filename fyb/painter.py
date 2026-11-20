"""画家：场景 → 图。只认 IR，不懂 DSL。"""
from __future__ import annotations

import math

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QFont, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QRadialGradient, QTransform)

from .blur import blur_image
from .canvas import Canvas, ensure_fonts
from .ir import Prim, Scene
from .pen import Stroke, build_stroke, stroke_path, to_qcolor
from .rng import Rng
from .texture import get_tile


# 混合模式：DSL 名字 → Qt 的合成模式。名单和 resolve.BLEND_MODES 一一对应。
_BLEND_QT = {
    "normal": QPainter.CompositionMode_SourceOver,
    "multiply": QPainter.CompositionMode_Multiply,
    "screen": QPainter.CompositionMode_Screen,
    "overlay": QPainter.CompositionMode_Overlay,
    "darken": QPainter.CompositionMode_Darken,
    "lighten": QPainter.CompositionMode_Lighten,
    "dodge": QPainter.CompositionMode_ColorDodge,
    "burn": QPainter.CompositionMode_ColorBurn,
    "softlight": QPainter.CompositionMode_SoftLight,
    "hardlight": QPainter.CompositionMode_HardLight,
    "difference": QPainter.CompositionMode_Difference,
    "exclusion": QPainter.CompositionMode_Exclusion,
    "add": QPainter.CompositionMode_Plus,
}


def _chaikin(pts, iterations=2, closed=True):
    """Chaikin 平滑。**开路径不能按闭合算**——否则两端会被拉在一起，
    整条线变成"去一趟再回来"，`along` 沿它分布时就会跑到反面去。"""
    out = list(pts)
    for _ in range(max(0, iterations)):
        if len(out) < 3:
            break
        nxt = []
        n = len(out)
        pairs = range(n) if closed else range(n - 1)
        if not closed:
            nxt.append(out[0])
        for i in pairs:
            x0, y0 = out[i]
            x1, y1 = out[(i + 1) % n]
            nxt.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            nxt.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        if not closed:
            nxt.append(out[-1])
        out = nxt
    return out


def _shape_path(prim: Prim) -> QPainterPath:
    path = QPainterPath()
    if prim.kind == "rect" and prim.rect:
        x, y, w, h = prim.rect
        if prim.radius:
            path.addRoundedRect(QRectF(x, y, w, h), prim.radius, prim.radius)
        else:
            path.addRect(QRectF(x, y, w, h))
        return path
    if prim.kind == "circle" and prim.rect:
        x, y, w, h = prim.rect
        path.addEllipse(QRectF(x, y, w, h))
        return path
    pts = prim.points
    if prim.kind == "curve" and prim.smooth > 0:
        pts = _chaikin(pts, 2 if prim.smooth >= 0.5 else 1, closed=prim.closed)
    if not pts:
        return path
    path.moveTo(*pts[0])
    for p in pts[1:]:
        path.lineTo(*p)
    if prim.closed:
        path.closeSubpath()
    return path


def _paint_grad(p: QPainter, prim: Prim, ctx=None):
    import math

    # grad ref=<形状>：渐变裁进那个形状里（形状可以是图元名，也可以是组名）。
    # 以前只能 clip + grad rect，还得自己手算包围盒 —— 估小了露白、估大了被拉平。
    ref = (prim.grad or {}).get("ref")
    if ref:
        path = _ref_path(ctx or {}, ref)
        if path.isEmpty():
            return
        box = path.boundingRect()
        if prim.grad.get("p0") is not None and prim.grad.get("p1") is not None:
            # 自定义轴：颜色沿 p0→p1 走，跟包围盒和角度无关
            a0 = prim.grad["p0"]
            a1 = prim.grad["p1"]
            brush = QLinearGradient(QPointF(a0[0], a0[1]), QPointF(a1[0], a1[1]))
        else:
            cx, cy = box.center().x(), box.center().y()
            ang = math.radians(float(prim.grad.get("dir", 90)))
            L = abs(box.width() * math.cos(ang)) + abs(box.height() * math.sin(ang))
            dx, dy = math.cos(ang) * L / 2, math.sin(ang) * L / 2
            brush = QLinearGradient(QPointF(cx - dx, cy - dy),
                                    QPointF(cx + dx, cy + dy))
        a = prim.alpha
        brush.setColorAt(0.0, to_qcolor(prim.grad.get("from", "#ffffff"), a))
        brush.setColorAt(1.0, to_qcolor(prim.grad.get("to", "#000000"), a))
        p.setPen(Qt.NoPen)
        p.setBrush(brush)
        p.drawPath(path)
        return

    if prim.rect:
        x, y, w, h = prim.rect
        path = QPainterPath()
        if prim.grad.get("radial"):
            path.addEllipse(QRectF(x, y, w, h))
            cx, cy, r = x + w / 2, y + h / 2, w / 2
            brush = QRadialGradient(QPointF(cx, cy), max(0.01, r))
        else:
            path.addRect(QRectF(x, y, w, h))
            cx, cy = x + w / 2, y + h / 2
            ang = math.radians(float(prim.grad.get("dir", 90)))
            L = abs(w * math.cos(ang)) + abs(h * math.sin(ang))
            dx, dy = math.cos(ang) * L / 2, math.sin(ang) * L / 2
            brush = QLinearGradient(QPointF(cx - dx, cy - dy), QPointF(cx + dx, cy + dy))
    else:
        path = _shape_path(prim)
        if path.isEmpty():
            return
        box = path.boundingRect()
        cx, cy = box.center().x(), box.center().y()
        ang = math.radians(float(prim.grad.get("dir", 90)))
        L = abs(box.width() * math.cos(ang)) + abs(box.height() * math.sin(ang))
        dx, dy = math.cos(ang) * L / 2, math.sin(ang) * L / 2
        brush = QLinearGradient(QPointF(cx - dx, cy - dy), QPointF(cx + dx, cy + dy))

    a = prim.alpha
    c0 = to_qcolor(prim.grad.get("from", "#ffffff"), a)
    c1 = to_qcolor(prim.grad.get("to", "#000000"), a)
    brush.setColorAt(0.0, c0)
    brush.setColorAt(1.0, c1)
    p.setPen(Qt.NoPen)
    p.setBrush(brush)
    p.drawPath(path)


def _text_path(prim: Prim, rng) -> QPainterPath:
    """把文字变成路径；`hand` 越大，字形轮廓抖得越厉害。

    取字形的轮廓棱点（toSubpathPolygons 会先把贝塞尔掰成折线），每个点抖一点，
    再拼回路径填充 —— 不需要任何笔画数据，中文也能"手写"。
    """
    from PySide6.QtGui import QFontMetricsF

    ensure_fonts()
    font = QFont(prim.font)
    font.setPixelSize(max(1, int(round(prim.size))))
    path = QPainterPath()
    path.addText(0.0, 0.0, font, prim.text)

    metrics = QFontMetricsF(font)
    width = metrics.horizontalAdvance(prim.text)
    dx = 0.0
    if prim.align == "center":
        dx = -width / 2
    elif prim.align == "right":
        dx = -width
    x, y = prim.points[0]
    path.translate(x + dx, y)

    if prim.hand <= 0:
        return path

    amp = prim.hand * prim.size * 0.055
    out = QPainterPath()
    out.setFillRule(Qt.WindingFill)
    for poly in path.toSubpathPolygons():
        if poly.size() < 3:
            continue
        pts = [(p.x() + (rng.next() * 2 - 1) * amp,
                p.y() + (rng.next() * 2 - 1) * amp) for p in poly]
        out.moveTo(*pts[0])
        for q in pts[1:]:
            out.lineTo(*q)
        out.closeSubpath()
    return out


def _paint_hatch(p: QPainter, prim: Prim, ctx, rng, scale: float):
    """在引用的形状里排一排平行的线，每条都用笔画出来（有起收和微抖）。"""
    import math

    path = _ref_path(ctx, prim.ref or "")
    if path.isEmpty():
        return
    box = path.boundingRect()
    if box.width() <= 0 or box.height() <= 0:
        return

    p.save()
    p.setClipPath(path, Qt.IntersectClip)
    p.setPen(Qt.NoPen)
    p.setBrush(to_qcolor(prim.stroke or "#1f2937", prim.alpha))

    a = math.radians(float(prim.grad.get("angle", 45)))
    spacing = max(2.0, float(prim.grad.get("spacing", 18)))
    diag = math.hypot(box.width(), box.height())
    cx, cy = box.center().x(), box.center().y()
    nx, ny = -math.sin(a), math.cos(a)
    steps = int(diag / spacing / 2) + 1
    pen = prim.pen or {}

    for i in range(-steps, steps + 1):
        ox, oy = cx + nx * spacing * i, cy + ny * spacing * i
        half = diag / 2
        p0 = (ox - math.cos(a) * half, oy - math.sin(a) * half)
        p1 = (ox + math.cos(a) * half, oy + math.sin(a) * half)
        st = Stroke(points=[p0, p1], width=pen.get("width", 3.0),
                    color=prim.stroke or "#1f2937", alpha=prim.alpha,
                    jitter=pen.get("jitter", 0.6), roughness=pen.get("roughness", 1.0),
                    taper=pen.get("taper", 0.5), press=pen.get("press"),
                    overshoot=0.0, wave=0.0,
                    wavelength=pen.get("wavelength", 48.0),
                    resample_step=pen.get("step", 6.0))
        pts, widths = build_stroke(st, rng)
        if len(pts) >= 2:
            p.drawPath(stroke_path(pts, widths))
    p.restore()


def _paint_pathop(p: QPainter, prim: Prim, ctx):
    base = _ref_path(ctx, prim.grad.get("base", ""))
    other = _ref_path(ctx, prim.grad.get("with", ""))
    if base.isEmpty() or other.isEmpty():
        return
    op = prim.grad.get("op", "subtract")
    if op == "union":
        path = base.united(other)
    elif op == "intersect":
        path = base.intersected(other)
    else:
        path = base.subtracted(other)
    if prim.fill:
        p.setPen(Qt.NoPen)
        p.setBrush(to_qcolor(prim.fill, prim.alpha))
        p.drawPath(path)
    if prim.stroke and prim.width > 0:
        qp = QPen(to_qcolor(prim.stroke, prim.alpha))
        qp.setWidthF(max(0.1, prim.width))
        qp.setCapStyle(Qt.RoundCap)
        qp.setJoinStyle(Qt.RoundJoin)
        p.setPen(qp)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def _paint_along(p: QPainter, prim: Prim, ctx, scale: float, base_seed: int,
                 depth: int = 0):
    """沿一条路径等距复制一组东西（头饰的褶边、沿边的铆钉、一串脚印）。"""
    from .rng import Rng, seed_hash

    if depth > 6:                      # 解析期已查过环，这里只是兜底
        return
    refp = _ref_path(ctx, prim.grad.get("ref", ""))
    idxs = ctx["groups"].get(prim.grad.get("group", ""), [])
    if refp.isEmpty() or not idxs:
        return
    count = max(1, int(prim.grad.get("count", 5)))
    s = float(prim.grad.get("scale", 1.0))
    use_rot = bool(prim.grad.get("rot", 1))
    scene = ctx["scene"]

    # use 复制出来的 along 带着一层变换（它自己没有几何可以改坐标）
    if prim.mate is not None:
        p.save()
        p.setTransform(QTransform(*prim.mate), True)

    for i in range(count):
        t = (i + 0.5) / count
        pt = refp.pointAtPercent(t)
        p.save()
        p.translate(pt)
        if use_rot:
            p.rotate(-refp.angleAtPercent(t))
        p.scale(s, s)
        for j in idxs:
            child = scene.prims[j]
            if child.kind == "shadow":
                continue
            if child.kind == "along":
                # 嵌套 along：画笔的变换会自己复合 —— 内层的 ref 路径和模板
                # 坐标都写在外层模板的局部系里，所以不用手动换算。
                # 以前这里是 continue，后果是**静默少画**，而且编译不报错。
                _paint_along(p, child, ctx, scale, base_seed, depth + 1)
                continue
            if child.kind == "pathop":
                continue
            rng = Rng(seed_hash(base_seed, f"along{prim.line}#{i}", f"p{j}"))
            _paint_prim(p, child, scale, rng, ctx, base_seed)
        p.restore()

    if prim.mate is not None:
        p.restore()


def _mean_angle(pts) -> float:
    """一条笔画的平均走向（度）。纹理按这个角度转，才会"顺着笔走"。"""
    import math as _m
    if len(pts) < 2:
        return 0.0
    sx = sy = 0.0
    for i in range(1, len(pts)):
        dx = pts[i][0] - pts[i - 1][0]
        dy = pts[i][1] - pts[i - 1][1]
        d = _m.hypot(dx, dy)
        if d < 1e-9:
            continue
        # 按长度加权，避免短段抖动主导方向
        sx += dx / d * d
        sy += dy / d * d
    if abs(sx) < 1e-9 and abs(sy) < 1e-9:
        return 0.0
    return _m.degrees(_m.atan2(sy, sx))


def _draw_ink(p: QPainter, pts, widths, st: Stroke, prim: Prim, rng: Rng,
              scale: float) -> None:
    """画一笔。没有纹理、只画一遍的时候走最便宜的直画；
    有纹理或多遍（干笔）时，先画到一层，乘上遮罩再合成。"""
    tex = (prim.grad or {}).get("tex") if isinstance(prim.grad, dict) else None
    tex = tex or ""
    passes = int(prim.grad.get("passes", 1)) if isinstance(prim.grad, dict) else 1
    spread = float(prim.grad.get("spread", 0.35)) if isinstance(prim.grad, dict) else 0.35
    tex_scale = float(prim.grad.get("tex_scale", 1.0)) if isinstance(prim.grad, dict) else 1.0
    tex_alpha = float(prim.grad.get("tex_alpha", 1.0)) if isinstance(prim.grad, dict) else 1.0

    if not tex and passes <= 1:
        path = stroke_path(pts, widths, closed=st.closed, cap=st.cap)
        p.setPen(Qt.NoPen)
        p.setBrush(to_qcolor(st.color, st.alpha))
        p.drawPath(path)
        return

    # 有纹理时，笔宽本身也要抖 —— 只压 alpha 的话，细线上根本看不出来，
    # 看着还是矢量描边。让边"毛"起来才像铅笔。
    if tex and len(widths) > 2:
        n = len(widths)
        raw = [rng.next() for _ in range(n)]
        smooth = [(raw[max(0, i - 1)] + raw[i] * 2 + raw[min(n - 1, i + 1)]) / 4
                  for i in range(n)]
        widths = [w * (0.70 + 0.60 * s) for w, s in zip(widths, smooth)]

    # 多遍：每遍整体平移一点点，单遍太透明看不出东西，叠起来才有"擦上去"的层次
    if passes > 1:
        w = float(np.mean(widths)) if len(widths) else 4.0
        amp = max(0.6, w * spread)
        offsets = [(float(rng.next() * 2 - 1) * amp, float(rng.next() * 2 - 1) * amp)
                   for _ in range(passes)]
        base = st.alpha / max(1.0, passes * 0.62)
    else:
        offsets = [(0.0, 0.0)]
        base = st.alpha

    # 先算总包围盒（含偏移与笔宽），层只开这么大
    xs = [x for x, _ in pts]
    ys = [y for _, y in pts]
    pad = float(max(widths) if len(widths) else 4.0) + 8.0
    for dx, dy in offsets:
        pad = max(pad, abs(dx) + abs(dy) + 8.0)
    x0, y0 = min(xs) - pad, min(ys) - pad
    x1, y1 = max(xs) + pad, max(ys) + pad
    lw = max(1, int(round((x1 - x0) * scale)))
    lh = max(1, int(round((y1 - y0) * scale)))

    layer = QImage(lw, lh, QImage.Format_ARGB32_Premultiplied)
    layer.fill(0)
    lp = QPainter(layer)
    lp.setRenderHint(QPainter.Antialiasing, True)
    lp.scale(scale, scale)
    lp.translate(-x0, -y0)
    lp.setPen(Qt.NoPen)
    lp.setBrush(to_qcolor(st.color, 1.0))
    for dx, dy in offsets:
        shifted = [(x + dx, y + dy) for x, y in pts]
        lp.drawPath(stroke_path(shifted, widths, closed=st.closed, cap=st.cap))
    lp.end()

    if tex:
        tile = get_tile(tex, 1)
        if tile is not None:
            # 定向纸纹：把纹理**转到笔的方向**，并以这一笔的起点为锚。
            # 之前是直接平铺在画布空间——不管笔往哪走，纹理都钉在同一张纸上，
            # 所以 fiber 用在粗笔上会变成横向条纹，像麻绳。
            ang = _mean_angle(pts)
            k = tex_scale * scale
            t = QTransform()
            t.translate((pts[0][0] - x0) * scale, (pts[0][1] - y0) * scale)
            t.rotate(ang)
            t.scale(k, k)
            brush = QBrush(tile)
            brush.setTransform(t)
            mp = QPainter(layer)
            mp.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            if tex_alpha < 1.0:
                # 纹理弱一点：先画满再叠，避免整笔变淡
                mp.setOpacity(tex_alpha)
            mp.fillRect(layer.rect(), brush)
            mp.end()

    p.save()
    p.setPen(Qt.NoPen)
    p.setOpacity(base)
    p.drawImage(QRectF(x0, y0, x1 - x0, y1 - y0), layer)
    p.restore()


def _paint_prim(p: QPainter, prim: Prim, scale: float, rng: Rng,
                ctx=None, base_seed: int = 0):
    ctx = ctx or {"scene": None, "by_name": {}, "groups": {}}
    if prim.kind == "pathop":
        _paint_pathop(p, prim, ctx)
        return
    if prim.kind == "along":
        _paint_along(p, prim, ctx, scale, base_seed)
        return
    if prim.kind == "grad":
        _paint_grad(p, prim, ctx)
        return
    if prim.kind == "ink":
        pts = list(prim.points)
        pen = dict(prim.pen or {})
        st = Stroke(
            points=pts,
            width=pen.get("width", 3.0),
            color=prim.stroke or "#1f2937",
            alpha=prim.alpha,
            jitter=pen.get("jitter", 0.62),
            roughness=pen.get("roughness", 1.0),
            taper=pen.get("taper", 0.2),
            press=pen.get("press"),
            overshoot=pen.get("overshoot"),
            closed=prim.closed,
            pin_start=pen.get("pin_start", False),
            pin_end=pen.get("pin_end", False),
            wave=pen.get("wave", 0.0),
            wavelength=pen.get("wavelength", 48.0),
            resample_step=pen.get("step", 6.0),
        )
        from .pen import build_stroke
        jpts, widths = build_stroke(st, rng)
        if len(jpts) < 2:
            return
        _draw_ink(p, jpts, widths, st, prim, rng, scale)
        return

    if prim.kind == "text":
        pen_color = prim.stroke or prim.fill or "#1f2937"
        path = _text_path(prim, rng)
        p.setPen(Qt.NoPen)
        p.setBrush(to_qcolor(pen_color, prim.alpha))
        p.drawPath(path)
        return

    path = _shape_path(prim)
    if prim.fill:
        p.setPen(Qt.NoPen)
        p.setBrush(to_qcolor(prim.fill, prim.alpha))
        p.drawPath(path)
    # 带 w= 的曲线/多边形：用"笔"描边 —— 又平滑又有手味
    if prim.pen and prim.stroke and prim.pen.get("width", 0) > 0:
        pts = list(prim.points)
        if prim.kind == "curve" and prim.smooth > 0:
            pts = _chaikin(pts, 2 if prim.smooth >= 0.5 else 1, closed=prim.closed)
        pen = prim.pen
        st = Stroke(
            points=pts, width=pen.get("width", 3.0), color=prim.stroke,
            alpha=prim.alpha, jitter=pen.get("jitter", 0.62),
            roughness=pen.get("roughness", 1.0), taper=pen.get("taper", 0.2),
            press=pen.get("press"),
            overshoot=pen.get("overshoot") if not prim.closed else 0,
            closed=prim.closed, pin_start=False, pin_end=False,
            wave=pen.get("wave", 0.0), wavelength=pen.get("wavelength", 48.0),
            resample_step=pen.get("step", 6.0))
        from .pen import build_stroke
        jpts, widths = build_stroke(st, rng)
        if len(jpts) >= 2:
            _draw_ink(p, jpts, widths, st, prim, rng, scale)
        return
    if prim.stroke and prim.width > 0:
        qp = QPen(to_qcolor(prim.stroke, prim.alpha))
        qp.setWidthF(max(0.1, prim.width))
        qp.setCapStyle(Qt.RoundCap)
        qp.setJoinStyle(Qt.RoundJoin)
        p.setPen(qp)
        p.setBrush(Qt.NoBrush)
        p.drawPath(path)


def _ref_path(ctx, ref: str) -> QPainterPath:
    """把"名字"变成一条路径：图元名就是它自己，组名是组内所有形状的并。"""
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    scene = ctx["scene"]
    if ref in ctx["groups"]:
        for idx in ctx["groups"][ref]:
            p = scene.prims[idx]
            if p.kind in ("rect", "circle", "curve", "poly", "grad"):
                path.addPath(_shape_path(p))
        return path
    prim = ctx["by_name"].get(ref)
    if prim is not None and prim.kind in ("rect", "circle", "curve", "poly", "grad"):
        path.addPath(_shape_path(prim))
    return path


def _paint_shadow(p: QPainter, prim: Prim, ctx, scale: float):
    path = _ref_path(ctx, prim.ref or "")
    if path.isEmpty():
        return
    moved = QPainterPath(path)
    moved.translate(prim.dx, prim.dy)

    if prim.blur < 0.5:
        p.save()
        p.setPen(Qt.NoPen)
        p.setBrush(to_qcolor(prim.fill or "#000000", prim.alpha))
        p.drawPath(moved)
        p.restore()
        return

    # 软阴影：把轮廓画到一张小图上 → 模糊 → 合成。
    # 只开 bbox+3σ 那么大，不占整张画布。
    pad = prim.blur * 3
    box = moved.boundingRect().adjusted(-pad, -pad, pad, pad)
    w = max(1, int(round(box.width() * scale)))
    h = max(1, int(round(box.height() * scale)))
    layer = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    layer.fill(0)
    lp = QPainter(layer)
    lp.setRenderHint(QPainter.Antialiasing, True)
    lp.scale(scale, scale)
    lp.translate(-box.x(), -box.y())
    lp.setPen(Qt.NoPen)
    lp.setBrush(to_qcolor(prim.fill or "#000000", 1.0))
    lp.drawPath(moved)
    lp.end()

    soft = blur_image(layer, prim.blur * scale)
    p.save()
    p.setPen(Qt.NoPen)
    p.setOpacity(prim.alpha)
    p.drawImage(QRectF(box.x(), box.y(), box.width(), box.height()), soft)
    p.restore()


def _unit_draw(p: QPainter, unit: list[Prim], cv, ctx, base: int,
               state: dict, scale: float) -> None:
    """把一串连续图元画到当前 painter 上（clip / blend 状态自己管）。"""
    from .rng import seed_hash

    for prim in unit:
        if prim.blend != state["blend"]:
            p.setCompositionMode(_BLEND_QT.get(prim.blend,
                                               QPainter.CompositionMode_SourceOver))
            state["blend"] = prim.blend
        if prim.clip != state["clip"]:
            p.setClipping(False)
            state["clip"] = prim.clip
            for name in (prim.clip or ()):
                cp = _ref_path(ctx, name)
                if not cp.isEmpty():
                    p.setClipPath(cp, Qt.IntersectClip)
        if prim.kind == "shadow":
            _paint_shadow(p, prim, ctx, scale)
        elif prim.kind == "hatch":
            hrng = Rng(seed_hash(base, prim.name or f"@{prim.line}", "hatch"))
            _paint_hatch(p, prim, ctx, hrng, scale)
        else:
            # 每一笔自己的种子：按名字散列（没名字退回行号）。
            # 这样在上面插一笔，下面的笔不会跟着重新抖 —— 不然改一行整张图都在动，
            # 我就分不清"是改动变好了"还是"恰好抖到了"。
            key = prim.name or f"@{prim.line}"
            rng = Rng(seed_hash(base, key, prim.kind))
            _paint_prim(p, prim, scale, rng, ctx, base)
        cv.ops += 1
    # 一笔画完要撤掉裁剪（否则会带到下一笔），**同时必须把状态也清掉**。
    # 只撤不记，下一个图元比对"状态 == 自己的 clip"会以为已经裁好了，
    # 于是直接画到裁剪外面 —— 橙子外面那圈红晕就是这么来的。
    p.setClipping(False)
    state["clip"] = ()


def _split_units(prims: list[Prim], limit: int | None) -> list[list[Prim]]:
    """把图元切成"直接画"和"整块模糊"两类。同一 blur_id 的连续段算一个单元。

    组层边界也必须切开：一个单元只能属于一条组链，否则合成时会用错层。
    """
    units: list[list[Prim]] = []
    cur: list[Prim] = []
    cur_id = 0
    cur_groups: tuple[int, ...] = ()
    count = 0
    for prim in prims:
        if limit is not None and count >= limit:
            break
        if prim.invisible:
            continue
        if prim.blur_id == 0 or prim.groups != cur_groups:
            if cur:
                units.append(cur)
                cur = []
            cur_groups = prim.groups
            if prim.blur_id == 0:
                units.append([prim])
                count += 1
                continue
            cur_id = prim.blur_id
            cur.append(prim)
            count += 1
            continue
        if cur and cur_id != prim.blur_id:
            units.append(cur)
            cur = []
        cur_id = prim.blur_id
        cur.append(prim)
        count += 1
    if cur:
        units.append(cur)
    return units


def _prim_bounds(prim: Prim, ctx) -> QRectF | None:
    """估一个图元的包围盒（逻辑坐标）。拿不准就返回 None，调用方退回全画布。"""
    kind = prim.kind
    if kind == "grad" and (prim.grad or {}).get("ref"):
        # 形状内渐变：包围盒跟着那个形状走（否则模糊层会开成全画布）
        r = _prim_bounds_by_ref(prim.grad["ref"], ctx)
        return r.adjusted(-2, -2, 2, 2) if r is not None else None
    if kind in ("curve", "poly", "rect", "circle", "grad"):
        path = _shape_path(prim)
        if path.isEmpty():
            return None
        r = path.boundingRect()
        if prim.pen and prim.pen.get("width"):
            w = float(prim.pen["width"]) * 1.6 + 8
            r = r.adjusted(-w, -w, w, w)
        elif prim.width > 0:
            w = prim.width * 1.5 + 6
            r = r.adjusted(-w, -w, w, w)
        return r
    if kind == "ink":
        if not prim.points:
            return None
        xs = [p[0] for p in prim.points]
        ys = [p[1] for p in prim.points]
        w = float((prim.pen or {}).get("width", 4)) * 2.0 + 12
        return QRectF(min(xs) - w, min(ys) - w,
                      max(xs) - min(xs) + 2 * w, max(ys) - min(ys) + 2 * w)
    if kind == "shadow":
        r = _prim_bounds_by_ref(prim.ref, ctx)
        if r is None:
            return None
        r = r.translated(prim.dx, prim.dy)
        pad = prim.blur * 3 + 2
        return r.adjusted(-pad, -pad, pad, pad)
    if kind == "hatch":
        return _prim_bounds_by_ref(prim.ref, ctx)
    return None                       # text / along / pathop：保守，用全画布


def _prim_bounds_by_ref(ref: str | None, ctx) -> QRectF | None:
    if not ref:
        return None
    scene = ctx.get("scene")
    if scene is None:
        return None
    if ref in ctx["groups"]:
        box = QRectF()
        for idx in ctx["groups"][ref]:
            r = _prim_bounds(scene.prims[idx], ctx)
            if r is None:
                return None
            box = r if box.isNull() else box.united(r)
        return None if box.isNull() else box
    p = ctx["by_name"].get(ref)
    return _prim_bounds(p, ctx) if p is not None else None


def render(scene: Scene, scale: int = 2, fast: bool = False, seed: int | None = None,
           under=None, under_alpha: float = 0.35,
           max_ops: int | None = None) -> Canvas:
    """max_ops：只画前 N 个图元（逐笔动画用）。"""
    cv = Canvas(scene.width, scene.height, bg=scene.bg, scale=1 if fast else scale)
    painter = cv.painter
    painter.setRenderHint(QPainter.Antialiasing, not fast)
    if under is not None:
        # 垫底稿：参考图按画布高度等比缩放、水平居中，铺在场景下面
        ref = QImage(str(under))
        if not ref.isNull():
            h = scene.height
            w = int(round(ref.width() * h / ref.height()))
            ref = ref.scaledToHeight(h, Qt.SmoothTransformation)
            painter.setOpacity(max(0.0, min(1.0, under_alpha)))
            painter.drawImage(QPointF((scene.width - w) / 2, 0), ref)
            painter.setOpacity(1.0)
    ctx = {
        "scene": scene,
        "by_name": {p.name: p for p in scene.prims if p.name},
        "groups": scene.groups,
    }
    base = seed if seed is not None else int((scene.hand or {}).get("seed", 7))
    ordered = sorted(scene.prims, key=lambda x: x.z)
    # 状态字典必须**跨图元一直用同一个**：它记录的是"画笔现在处于什么模式"。
    # 每个图元新建一个，就会变成"字典说 normal、画笔还停在 screen"，
    # 于是不会重置混合模式 —— 一整片画面被上一个 blend 块洗白（室内那张就是这么翻车的）。
    state = {"clip": (), "blend": "normal"}
    # 模糊层的包围盒最多到这里（整张画布）
    empty = QRectF(0, 0, scene.width, scene.height)

    # ── 组透明：每个带 alpha 的组各开一层，按 z 序进出 ──────────────
    # 层的大小按"这个组里所有图元的并集"算，不占整张画布。
    gbox: dict[int, QRectF] = {}
    galpha = dict(getattr(scene, "group_alpha", {}) or {})
    for prim in ordered:
        for gid in prim.groups:
            if gid not in galpha:
                continue
            r = _prim_bounds(prim, ctx)
            if r is None:
                gbox[gid] = empty
            elif gid in gbox and not gbox[gid].isNull():
                gbox[gid] = gbox[gid].united(r)
            else:
                gbox[gid] = QRectF(r)

    open_groups: list[dict] = []

    def target():
        return open_groups[-1]["painter"] if open_groups else painter

    def close_top():
        g = open_groups.pop()
        g["painter"].end()
        tp = target()
        tp.save()
        tp.setOpacity(g["alpha"])
        tp.drawImage(g["box"], g["img"])
        tp.restore()

    def settle(chain: tuple[int, ...]):
        """把栈收拢到 chain 的前缀长度，多出来的层按序合成。"""
        keep = 0
        while keep < len(open_groups) and keep < len(chain) \
                and open_groups[keep]["gid"] == chain[keep]:
            keep += 1
        while len(open_groups) > keep:
            close_top()
        for gid in chain[keep:]:
            box = gbox.get(gid) or empty
            box = box.adjusted(-2, -2, 2, 2).intersected(empty)
            if box.width() < 2 or box.height() < 2:
                box = empty
            img = QImage(max(1, int(round(box.width() * cv.scale))),
                         max(1, int(round(box.height() * cv.scale))),
                         QImage.Format_ARGB32_Premultiplied)
            img.fill(0)
            gp = QPainter(img)
            gp.setRenderHint(QPainter.Antialiasing, not fast)
            gp.scale(cv.scale, cv.scale)
            gp.translate(-box.x(), -box.y())
            open_groups.append({"gid": gid, "alpha": float(galpha.get(gid, 1.0)),
                                "box": box, "img": img, "painter": gp})

    for unit in _split_units(ordered, max_ops):
        settle(unit[0].groups)
        tp = target()
        # 换了一支画笔（进/出组层），状态要重来
        if state.get("painter") is not tp:
            state = {"clip": (), "blend": "normal", "painter": tp}

        if len(unit) == 1 and unit[0].blur_id == 0:
            _unit_draw(tp, unit, cv, ctx, base, state, cv.scale)
            continue

        # 整块模糊：只开"这一块图元"那么大的层，不占整张画布。
        # 之前按全画布开层，1920×1080@2× 每层就是 3840×2160 的图，
        # 一张有五个模糊块的画要 6 秒多；按包围盒开层后回到 1 秒以内。
        radius = float(unit[0].blur_radius)
        pad = radius * 3 + 4
        box = QRectF()
        for prim in unit:
            r = _prim_bounds(prim, ctx)
            if r is None:
                box = empty
                break
            box = r if box.isNull() else box.united(r)
        if box.isNull() or box.isEmpty():
            box = empty
        box = box.adjusted(-pad, -pad, pad, pad).intersected(empty)
        if box.width() < 2 or box.height() < 2:
            continue
        lw = max(1, int(round(box.width() * cv.scale)))
        lh = max(1, int(round(box.height() * cv.scale)))
        layer = QImage(lw, lh, QImage.Format_ARGB32_Premultiplied)
        layer.fill(0)
        lp = QPainter(layer)
        lp.setRenderHint(QPainter.Antialiasing, not fast)
        lp.scale(cv.scale, cv.scale)
        lp.translate(-box.x(), -box.y())
        # 层里的画笔是全新的，所以这里该用一份新状态
        _unit_draw(lp, unit, cv, ctx, base, {"clip": (), "blend": "normal"}, cv.scale)
        lp.end()
        soft = blur_image(layer, radius * cv.scale)
        tp.save()
        tp.setOpacity(unit[0].blur_alpha)
        tp.drawImage(box, soft)
        tp.restore()

    settle(())          # 收掉还没合完的组层

    painter.setClipping(False)
    painter.setCompositionMode(QPainter.CompositionMode_SourceOver)
    cv.finish()      # 画完就收尾：留着活动的 painter 会让 Qt 在退出时报错
    return cv
