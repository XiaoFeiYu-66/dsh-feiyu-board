"""小飞鱼画板 · 笔。

从 dsh-scribble 的 `lib/render.js` 逐行移植（MIT）。移植原则：
**参数名、取值范围、默认值、随机数消耗顺序全部一致**，这样
① 风格画像参数可以互通；② 能拿 JS 版当 oracle 做数值对照。

改动只有两处，都是刻意的：
- 笔形不再逐段画胶囊，而是把左右两条偏移线合成一个闭合路径（Qt 一次填充，
  带 alpha 时不会因为重叠而叠深）；
- 加了一个可选的 `resample_step`：JS 那边要手工重采样，这边做成笔的默认行为。
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainterPath

from .rng import Rng

# 与 scribble 默认值保持一致
DEFAULT_WIDTH = 3.0
DEFAULT_JITTER = 0.62
DEFAULT_TAPER = 0.2
DEFAULT_WAVE = 0.55
DEFAULT_FREQUENCY = 0.55
TAPER_END_OPEN = 0.66
TAPER_END_CLOSED = 0.9


@dataclass
class Stroke:
    points: list[tuple[float, float]]
    width: float = DEFAULT_WIDTH
    widths: list[float] | None = None
    color: str = "#1f2937"
    alpha: float = 1.0
    jitter: float = DEFAULT_JITTER
    roughness: float = 1.0
    taper: float = DEFAULT_TAPER
    overshoot: float | None = None
    closed: bool = False
    pin_start: bool = False
    pin_end: bool = False
    wave: float = DEFAULT_WAVE
    resample_step: float | None = None   # None = 不重采样（与 JS 对齐时必须关）
    wavelength: float | None = None      # 抖动的空间波长；None = 逐点噪声（与 JS 一致）
    cap: str = "round"
    # 笔压曲线：沿笔长的宽度倍率，2~5 个数（起点 → 终点）。
    # 和 taper 不是一回事：taper 是"两头自然收细"，press 是"这一笔按了多重"。
    press: tuple[float, ...] | None = None


# --------------------------------------------------------------------------- #
# 几何工具（纯 math，无 Qt 依赖，方便单测）
# --------------------------------------------------------------------------- #

def normalize_closed(points):
    """闭合笔画的点和点重合时，去掉最后一点（与 JS 同）。"""
    if not points or len(points) < 3:
        return list(points)
    (x0, y0), (x1, y1) = points[0], points[-1]
    if math.hypot(x1 - x0, y1 - y0) < 0.001:
        return list(points[:-1])
    return list(points)


def resample(points, step: float):
    """按弧长等距重采样。**手味的前提**：抖是按点算的，两点直线抖不起来。"""
    if len(points) < 2 or step <= 0:
        return list(points)
    out = [tuple(points[0])]
    for i in range(1, len(points)):
        x0, y0 = points[i - 1]
        x1, y1 = points[i]
        d = math.hypot(x1 - x0, y1 - y0)
        n = max(1, int(round(d / step)))
        for k in range(1, n + 1):
            t = k / n
            out.append((x0 + (x1 - x0) * t, y0 + (y1 - y0) * t))
    return out


def chaikin(points, iterations=2):
    """闭合折线平滑：把折角磨圆。画笔和沿路径分布都用它。"""
    out = list(points)
    for _ in range(max(0, iterations)):
        if len(out) < 3:
            break
        nxt = []
        n = len(out)
        for i in range(n):
            x0, y0 = out[i]
            x1, y1 = out[(i + 1) % n]
            nxt.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            nxt.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        out = nxt
    return out


def sample_polyline(points, count, closed=False):
    """在折线上等距取 count 个点，返回 [(x, y, 切线角弧度)]。"""
    if len(points) < 2 or count <= 0:
        return []
    pts = list(points) + ([points[0]] if closed else [])
    segs = []
    total = 0.0
    for i in range(1, len(pts)):
        d = math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
        if d > 1e-9:
            segs.append((pts[i - 1], pts[i], d, total))
            total += d
    if not segs:
        return []
    out = []
    for k in range(count):
        target = total * (k + 0.5) / count
        for a, b, d, start in segs:
            if start + d >= target or (a, b, d, start) == segs[-1]:
                t = (target - start) / d
                t = max(0.0, min(1.0, t))
                x = a[0] + (b[0] - a[0]) * t
                y = a[1] + (b[1] - a[1]) * t
                ang = math.atan2(b[1] - a[1], b[0] - a[0])
                out.append((x, y, ang))
                break
    return out


def jitter_points(points, amplitude, rng: Rng, *, closed=False,
                  pin_start=False, pin_end=False, wave=0.0,
                  frequency=DEFAULT_FREQUENCY, wavelength=None, spacing=None):
    """抖动。

    默认路径与 scribble 的 jitterPoints 逐行一致（逐点噪声 + [1,2,1] 平滑）。
    `wavelength` 是可选的**第二个模式**：在粗格点上取噪声再线性插值，
    得到"波长几十像素"的手抖。为什么需要它见 tools/m0_sheet.py 的结论：
    逐点噪声在密采样下会变成锯齿，不像手，像锯条。
    """
    if len(points) < 2 or amplitude <= 0:
        return list(points)
    n = len(points)

    def at(i):
        if closed:
            return (i + n) % n
        return max(0, min(n - 1, i))

    phase = rng.next() * math.pi * 2

    if wavelength and spacing and wavelength > spacing * 1.5:
        k = max(1.0, wavelength / spacing)
        m = int(math.ceil(n / k)) + 2
        gx = [(rng.next() * 2 - 1) * amplitude for _ in range(m)]
        gy = [(rng.next() * 2 - 1) * amplitude for _ in range(m)]
        if not closed and pin_start:
            gx[0] = gy[0] = 0.0
        if not closed and pin_end:
            gx[-1] = gy[-1] = 0.0

        def _at(g, i):
            t = i / k
            j = min(int(math.floor(t)), m - 2)
            f = t - j
            f = f * f * (3 - 2 * f)          # smoothstep：线性插值会在格点上留下折角
            return g[j] * (1 - f) + g[j + 1] * f

        out = []
        for i in range(n):
            w = math.sin(i * frequency + phase) * amplitude * wave
            out.append((points[i][0] + _at(gx, i) + w,
                        points[i][1] + _at(gy, i) - w * 0.55))
        return out

    ox = [0.0] * n
    oy = [0.0] * n
    for i in range(n):
        ox[i] = (rng.next() * 2 - 1) * amplitude
        oy[i] = (rng.next() * 2 - 1) * amplitude
    if not closed and pin_start:
        ox[0] = 0.0
        oy[0] = 0.0
    if not closed and pin_end:
        ox[n - 1] = 0.0
        oy[n - 1] = 0.0

    out = []
    for i in range(n):
        a, b, c = ox[at(i - 1)], ox[at(i)], ox[at(i + 1)]
        d, e, f = oy[at(i - 1)], oy[at(i)], oy[at(i + 1)]
        w = math.sin(i * frequency + phase) * amplitude * wave
        out.append((points[i][0] + (a + 2 * b + c) / 4 + w,
                    points[i][1] + (d + 2 * e + f) / 4 - w * 0.55))
    return out


def apply_overshoot(points, overshoot, *, pin_start=False, pin_end=False):
    """线头冲出一点，像手停不住。"""
    if len(points) < 2 or overshoot <= 0 or pin_start or pin_end:
        return points
    pts = [list(p) for p in points]
    first, second = pts[0], pts[1]
    last, prev = pts[-1], pts[-2]
    d0 = math.hypot(first[0] - second[0], first[1] - second[1]) or 1.0
    d1 = math.hypot(last[0] - prev[0], last[1] - prev[1]) or 1.0
    first[0] += (first[0] - second[0]) / d0 * overshoot
    first[1] += (first[1] - second[1]) / d0 * overshoot
    last[0] += (last[0] - prev[0]) / d1 * overshoot
    last[1] += (last[1] - prev[1]) / d1 * overshoot
    return [(p[0], p[1]) for p in pts]


def press_profile(press, n: int) -> list[float]:
    """把笔压曲线（2~5 个倍率）线性插值成 n 个点。"""
    if not press or n <= 0:
        return [1.0] * n
    if len(press) == 1:
        return [float(press[0])] * n
    out = []
    last = len(press) - 1
    for i in range(n):
        t = 0.0 if n == 1 else i / (n - 1) * last
        k = min(int(t), last - 1)
        f = t - k
        out.append(press[k] * (1 - f) + press[k + 1] * f)
    return out


def taper_widths(points, width, taper, *, closed=False, press=None):
    """起收笔收细（正弦包络，与 JS 同）+ 笔压曲线（可选）。

    taper 管"一笔的两头自然收细"，press 管"这一笔中间按了多重"：
    两者相乘。press 是作者的手感，taper 是笔本身的物理。
    """
    n = len(points)
    end = TAPER_END_CLOSED if closed else TAPER_END_OPEN
    end = max(0.35, min(1.0, end))
    if (not taper or n < 3) and not press:
        return [width] * n
    if taper and n >= 3:
        base = [end + (1 - end) * math.sin(math.pi * (i / (n - 1))) for i in range(n)]
    else:
        base = [1.0] * n
    if press:
        prof = press_profile(press, n)
        base = [b * p for b, p in zip(base, prof)]
    return [width * b for b in base]


def build_stroke(s: Stroke, rng: Rng):
    """→ (最终点列, 逐点笔宽)。纯数学，不碰 Qt。"""
    pts = list(s.points)
    if s.resample_step:
        pts = resample(pts, s.resample_step)
    if s.closed:
        pts = normalize_closed(pts)
    if len(pts) < 2:
        return [], []

    amplitude = (s.jitter * (0.8 + max(0.0, s.width) * 0.38) + 0.16) * s.roughness
    spacing = s.resample_step
    if spacing is None and len(pts) > 1:
        total = sum(math.hypot(pts[i][0] - pts[i - 1][0], pts[i][1] - pts[i - 1][1])
                    for i in range(1, len(pts)))
        spacing = total / (len(pts) - 1)
    pts = jitter_points(pts, amplitude, rng, closed=s.closed,
                        pin_start=s.pin_start, pin_end=s.pin_end,
                        wave=s.wave, wavelength=s.wavelength or
                        (48.0 if s.resample_step else None), spacing=spacing)

    if not s.closed and s.widths is None:
        over = s.overshoot if s.overshoot is not None else s.width * 0.28 * s.roughness
        pts = apply_overshoot(pts, over,
                              pin_start=s.pin_start, pin_end=s.pin_end)

    widths = list(s.widths) if s.widths is not None else \
        taper_widths(pts, s.width, s.taper, closed=s.closed, press=s.press)
    return pts, widths[:len(pts)] + [widths[-1]] * max(0, len(pts) - len(widths))


# --------------------------------------------------------------------------- #
# 绘制
# --------------------------------------------------------------------------- #

def _unit(dx, dy):
    d = math.hypot(dx, dy)
    if d < 1e-9:
        return 0.0, 0.0
    return dx / d, dy / d


def stroke_path(pts, widths, *, closed=False, cap="round", mode="capsule"):
    """笔形。

    `capsule`（默认）：逐段画一个梯形 + 在每个顶点盖一个圆，全部塞进同一个
    QPainterPath 一次填充。好处是**永远不会自交**——用左右偏移线拼一条带子，
    在拐弯处左右会交叉，非零填充就咬出一个缺口，那种"锯齿"不是手抖，是几何错误。
    与 scribble 的逐段胶囊等价，但只做一次填充（alpha<1 时不会叠深）。

    `band`：左右偏移线合成闭合带（保留，方便对照）。
    """
    path = QPainterPath()
    # Qt 默认是奇偶填充 —— 一堆互相重叠的子路径会被"挖空"，变成虚线。
    path.setFillRule(Qt.WindingFill)
    if len(pts) < 2:
        return path
    if mode == "band":
        return _band_path(pts, widths, closed=closed, cap=cap)
    _capsule_path(path, pts, widths, closed=closed, cap=cap)
    return path


def _capsule_path(path: QPainterPath, pts, widths, *, closed, cap):
    """每段一个**单一闭合多边形**（含两端半圆）。

    为什么不是"梯形 + 单独的圆"：Qt 里圆和梯形朝向相反时，非零填充会把重叠处
    抵消掉（端头挖出一块白月牙）；奇偶填充更糟，整条笔会变成虚线。
    把半圆并进同一个多边形，所有段朝向一致，重叠处 winding 只会变大，不会再挖空。
    """
    n = len(pts)
    idx = range(n) if closed else range(n - 1)
    steps = 8
    for i in idx:
        j = (i + 1) % n
        x0, y0 = pts[i]
        x1, y1 = pts[j]
        dx, dy = x1 - x0, y1 - y0
        d = math.hypot(dx, dy)
        if d < 1e-9:
            continue
        ux, uy = dx / d, dy / d
        nx, ny = -uy, ux
        h0 = max(0.0, widths[i]) / 2.0
        h1 = max(0.0, widths[j]) / 2.0
        th = math.atan2(ny, nx)

        path.moveTo(x0 + nx * h0, y0 + ny * h0)
        path.lineTo(x1 + nx * h1, y1 + ny * h1)
        for k in range(1, steps + 1):
            a = th - math.pi * (k / steps)
            path.lineTo(x1 + math.cos(a) * h1, y1 + math.sin(a) * h1)
        path.lineTo(x0 - nx * h0, y0 - ny * h0)
        for k in range(1, steps + 1):
            a = th + math.pi - math.pi * (k / steps)
            path.lineTo(x0 + math.cos(a) * h0, y0 + math.sin(a) * h0)
        path.closeSubpath()


def _chaikin(poly, iterations=2):
    """闭合折线做 Chaikin 细分：把折角磨圆，边缘不再一格一格的。"""
    pts = list(poly)
    for _ in range(max(0, iterations)):
        if len(pts) < 3:
            break
        out = []
        n = len(pts)
        for i in range(n):
            x0, y0 = pts[i]
            x1, y1 = pts[(i + 1) % n]
            out.append((0.75 * x0 + 0.25 * x1, 0.75 * y0 + 0.25 * y1))
            out.append((0.25 * x0 + 0.75 * x1, 0.25 * y0 + 0.75 * y1))
        pts = out
    return pts


def _band_path(pts, widths, *, closed=False, cap="round", smooth=2) -> QPainterPath:
    """左右偏移线合成一条闭合带，再做 Chaikin 平滑。

    比逐段胶囊光滑（胶囊的每一段都是直的，放大看是一节一节的）；
    代价是急弯处偏移线可能自交，`smooth` 会把那点小毛刺磨掉。
    """
    path = QPainterPath()
    path.setFillRule(Qt.WindingFill)
    n = len(pts)
    if n < 2:
        return path

    left, right = [], []
    for i in range(n):
        if closed:
            dx = pts[(i + 1) % n][0] - pts[(i - 1) % n][0]
            dy = pts[(i + 1) % n][1] - pts[(i - 1) % n][1]
        elif i == 0:
            dx = pts[1][0] - pts[0][0]
            dy = pts[1][1] - pts[0][1]
        elif i == n - 1:
            dx = pts[-1][0] - pts[-2][0]
            dy = pts[-1][1] - pts[-2][1]
        else:
            dx = pts[i + 1][0] - pts[i - 1][0]
            dy = pts[i + 1][1] - pts[i - 1][1]
        ux, uy = _unit(dx, dy)
        nx, ny = -uy, ux
        h = max(0.0, widths[i]) / 2.0
        left.append((pts[i][0] + nx * h, pts[i][1] + ny * h))
        right.append((pts[i][0] - nx * h, pts[i][1] - ny * h))

    if closed:
        poly = left + list(reversed(right))
    else:
        # 圆头：两端各补半圈，凑成一个闭合多边形，再一起平滑
        poly = []
        if cap == "round":
            h0 = max(0.0, widths[0]) / 2.0
            hn = max(0.0, widths[-1]) / 2.0
            phi0 = math.atan2(pts[1][1] - pts[0][1], pts[1][0] - pts[0][0])
            phin = math.atan2(pts[-1][1] - pts[-2][1], pts[-1][0] - pts[-2][0])
            steps = 6
            for k in range(1, steps + 1):        # 右 → 绕尾 → 左
                a = (phi0 - math.pi / 2) - math.pi * (k / steps)
                poly.append((pts[0][0] + math.cos(a) * h0,
                             pts[0][1] + math.sin(a) * h0))
        poly += left
        if cap == "round":
            for k in range(1, steps + 1):        # 左 → 绕头 → 右
                a = (phin + math.pi / 2) - math.pi * (k / steps)
                poly.append((pts[-1][0] + math.cos(a) * hn,
                             pts[-1][1] + math.sin(a) * hn))
        poly += list(reversed(right))

    poly = _chaikin(poly, smooth)
    path.moveTo(*poly[0])
    for p in poly[1:]:
        path.lineTo(*p)
    path.closeSubpath()
    return path


def _add_cap(path: QPainterPath, center, start, end, r: float):
    """从 start 绕到 end 的半圆（顺时针还是逆时针由几何决定）。"""
    if r <= 0:
        path.lineTo(*start)
        return
    cx, cy = center
    a0 = math.atan2(start[1] - cy, start[0] - cx)
    a1 = math.atan2(end[1] - cy, end[0] - cx)
    # 走短的那边走（半圆）
    da = a1 - a0
    while da > math.pi:
        da -= 2 * math.pi
    while da < -math.pi:
        da += 2 * math.pi
    steps = 8
    for i in range(1, steps + 1):
        a = a0 + da * (i / steps)
        path.lineTo(cx + math.cos(a) * r, cy + math.sin(a) * r)


def to_qcolor(color: str, alpha: float = 1.0) -> QColor:
    text = str(color).strip()
    if text.startswith("#"):
        hexs = text[1:]
        if len(hexs) == 3:
            hexs = "".join(c + c for c in hexs)
        if len(hexs) in (6, 8):
            r = int(hexs[0:2], 16)
            g = int(hexs[2:4], 16)
            b = int(hexs[4:6], 16)
            a = int(hexs[6:8], 16) if len(hexs) == 8 else 255
            return QColor(r, g, b, int(round(a * max(0.0, min(1.0, alpha)))))
    named = {"ink": "#1f2937", "paper": "#f8f5ec", "black": "#000000",
             "white": "#ffffff"}
    return to_qcolor(named.get(text.lower(), "#1f2937"), alpha)
