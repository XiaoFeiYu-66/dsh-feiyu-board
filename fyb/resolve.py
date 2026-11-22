"""解析之后的第二遍：把命令变成场景。

这一层负责所有"需要看全局才知道对不对"的检查：
- 第一行是不是 canvas（E008）
- 组有没有配平（E006）
- 名字有没有重、引用有没有指向空气（E004 / E005）
- 数值在不在范围内（E007）、闭合图形点数够不够（E009）

**所有错误一次报全**：出错就记下来继续编译下一行，最后一起抛。
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from . import parser as P
from .errors import DslError
from .ir import Prim, Scene
from .texture import TEXTURES


@dataclass
class _Group:
    name: str | None
    mat: tuple[float, float, float, float, float, float]
    line: int
    start: int = 0
    template: bool = False


IDENTITY = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)

# 混合模式：名字 → Qt 的 CompositionMode（画家那边查表）
BLEND_MODES = ("normal", "multiply", "screen", "overlay", "darken", "lighten",
               "dodge", "burn", "softlight", "hardlight", "difference",
               "exclusion", "add")

# 手感预设（数值抄 dsh-scribble 的 style.js，只取笔画相关的几项）
HAND_PRESETS = {
    "clean":  {"jitter": 0.18, "taper": 0.20},
    "ink":    {"jitter": 0.30, "taper": 0.55},
    "pencil": {"jitter": 0.62, "taper": 0.38},
    "brush":  {"jitter": 0.42, "taper": 0.72},
    "child":  {"jitter": 1.18, "taper": 0.42},
    "messy":  {"jitter": 1.35, "taper": 0.34},
}

DEFAULT_HAND = {
    "jitter": 0.62, "taper": 0.2, "roughness": 1.0, "wave": 0.0,
    "wavelength": 48.0, "width": None, "step": 6.0, "seed": 7,
}


def compose(m, n):
    """先 n 后 m。"""
    a1, b1, c1, d1, e1, f1 = m
    a2, b2, c2, d2, e2, f2 = n
    return (a1 * a2 + c1 * b2, b1 * a2 + d1 * b2,
            a1 * c2 + c1 * d2, b1 * c2 + d1 * d2,
            a1 * e2 + c1 * f2 + e1, b1 * e2 + d1 * f2 + f1)


def apply(m, x, y):
    a, b, c, d, e, f = m
    return (a * x + c * y + e, b * x + d * y + f)


def _scale_of(m):
    a, b, c, d, _, _ = m
    return max(1e-6, math.hypot(a, b))


def build(commands: list[P.Command], source_lines: list[tuple[int, str]]) -> Scene:
    scene = Scene()
    scene.hand = dict(DEFAULT_HAND)
    errors: list[DslError] = []
    names: dict[str, int] = {}
    stack: list[_Group] = []
    cur = IDENTITY
    layer = 0.0
    seq = 0
    saw_canvas = False
    reported_missing_canvas = False
    clip_stack: list[str] = []
    blend_stack: list[str] = []
    blur_stack: list[tuple[int, float, float]] = []
    blur_seq = 0
    # 组透明：alpha_stack 记当前套在哪些"带 alpha 的组"里，group_depth 记每层
    # group 进入前的深度（退出时用它退回），gid_alpha 是组号 → alpha。
    alpha_stack: list[int] = []
    group_depth: list[int] = []
    alpha_counter = [0]
    gid_alpha: dict[int, float] = {}
    refs: list[tuple[str, P.Command, str]] = []

    def err(code, msg, cmd, col=None, length=1):
        errors.append(DslError(code, msg, cmd.line, col or cmd.col, length))

    def _tag(p: Prim, cmd: P.Command | None = None):
        """给新图元盖三个章：裁剪、混合模式、模板（不自己画）。"""
        # 嵌套 clip 要**全部记下来**。只留最内层的话，外层的裁剪被静默丢掉，
        # 画出来是错的但不报错 —— 这种"不吭声的错"最难查。
        if clip_stack:
            p.clip = tuple(clip_stack)
            for name in p.clip:
                refs.append((name, cmd, "clip"))
        if blend_stack:
            p.blend = blend_stack[-1]
        if blur_stack:
            bid, bradius, balpha = blur_stack[-1]
            p.blur_id = bid
            p.blur_radius = bradius
            p.blur_alpha = balpha
        # 组透明：记下自己套在哪几层"带 alpha 的组"里（外 → 内）。
        # 必须记整条链，只记最内层的话外层 alpha 会被静默丢掉。
        if alpha_stack:
            p.groups = tuple(alpha_stack)
        if any(g.template for g in stack):
            p.invisible = True

    for idx, cmd in enumerate(commands):
        verb, kw, pos = cmd.verb, cmd.kw, cmd.pos

        if idx == 0 and verb != "canvas":
            err("E008", "第一行必须是 canvas WxH", cmd)
            reported_missing_canvas = True
            continue
        if verb == "canvas":
            if saw_canvas:
                err("E014", "canvas 只能出现一次", cmd)
                continue
            saw_canvas = True
            w, h = P.as_pair(pos[0].replace("x", ","), "canvas 尺寸", cmd.line, cmd.col)
            if not (64 <= w <= 8192 and 64 <= h <= 8192):
                err("E007", f"画布要在 64~8192 之间，收到 {w:g}×{h:g}", cmd)
                continue
            scene.width, scene.height = int(round(w)), int(round(h))
            continue

        if verb == "bg":
            scene.bg = P.as_color(pos[0], "bg", cmd.line, cmd.col)
            continue

        if verb == "group":
            # 语义：at 是组的原点；scale/rot/flip 都绕着这个原点做。
            # 所以矩阵按 T ∘ R ∘ S ∘ F 的顺序拼（先翻，再缩，再转，最后平移）。
            mat = IDENTITY
            if "flip" in kw:
                f = kw["flip"].strip().lower()
                if f == "x":
                    mat = compose((-1, 0, 0, 1, 0, 0), mat)
                elif f == "y":
                    mat = compose((1, 0, 0, -1, 0, 0), mat)
                else:
                    err("E012", f"flip 只能是 x 或 y，收到 {f!r}", cmd,
                        cmd.kw_col("flip"), len(f))
            if "scale" in kw:
                s = P.as_float(kw["scale"], "group scale", cmd.line, cmd.kw_col("scale"))
                P.as_range(s, 0.01, 100, "group scale", cmd.line, cmd.kw_col("scale"))
                mat = compose((s, 0, 0, s, 0, 0), mat)
            if "rot" in kw:
                deg = P.as_float(kw["rot"], "group rot", cmd.line, cmd.kw_col("rot"))
                r = math.radians(deg)
                mat = compose((math.cos(r), math.sin(r), -math.sin(r),
                               math.cos(r), 0, 0), mat)
            if "about" in kw:
                # 绕某个点做缩放/旋转：T(C) ∘ M ∘ T(-C)。必须排在 at 前面，
                # 否则平移也会被"绕点"带着走。
                cx, cy = P.as_pair(kw["about"], "group about", cmd.line,
                                   cmd.kw_col("about"))
                mat = compose((1, 0, 0, 1, cx, cy),
                              compose(mat, (1, 0, 0, 1, -cx, -cy)))
            if "at" in kw:
                x, y = P.as_pair(kw["at"], "group at", cmd.line, cmd.kw_col("at"))
                mat = compose((1, 0, 0, 1, x, y), mat)
            name = kw.get("name") or (pos[0] if pos else None)
            if name is not None:
                if not P.NAME_RE.match(name):
                    err("E004", f"名字只能用字母/数字/下划线/汉字，收到 {name!r}",
                        cmd, cmd.kw_col("name"), len(name))
                elif name in names:
                    err("E004", f"名字 {name!r} 已经用过了（第 {names[name]} 行）",
                        cmd, cmd.kw_col("name"), len(name))
                else:
                    names[name] = cmd.line
            stack.append(_Group(name, compose(cur, mat), cmd.line,
                                len(scene.prims),
                                template=P.as_bool(kw.get("template", "0"))))
            # 组透明：alpha<1 的组要单独开一层再整体合成，
            # 这样组内图元重叠的地方不会叠出深色（跟逐个调小 alpha 不一样）。
            ga = P.as_range(P.as_float(kw.get("alpha", "1"), "group alpha", cmd.line,
                                       cmd.kw_col("alpha")),
                            0, 1, "group alpha", cmd.line, cmd.kw_col("alpha"))
            group_depth.append(len(alpha_stack))     # 进入这层之前的深度
            if ga < 0.999:
                alpha_counter[0] += 1
                gid = alpha_counter[0]
                gid_alpha[gid] = ga
                alpha_stack.append(gid)
            cur = stack[-1].mat
            continue

        if verb == "endgroup":
            if not stack:
                err("E006", "endgroup 多了（前面没有 group）", cmd)
                continue
            g = stack.pop()
            if group_depth:
                del alpha_stack[group_depth.pop():]   # 退出这一层，退回原深度
            if g.name:
                scene.groups[g.name] = list(range(g.start, len(scene.prims)))
            cur = stack[-1].mat if stack else IDENTITY
            continue

        if verb == "clip":
            clip_stack.append(pos[0])
            continue

        if verb == "endclip":
            if not clip_stack:
                err("E006", "endclip 多了（前面没有 clip）", cmd)
                continue
            clip_stack.pop()
            continue

        if verb == "blend":
            mode = pos[0].strip().lower()
            if mode not in BLEND_MODES:
                err("E012", f"blend 不认识 {mode!r}；可用：{', '.join(BLEND_MODES)}", cmd)
                continue
            blend_stack.append(mode)
            continue

        if verb == "endblend":
            if not blend_stack:
                err("E006", "endblend 多了（前面没有 blend）", cmd)
                continue
            blend_stack.pop()
            continue

        if verb == "shadow":
          try:
            ref = kw.get("ref", "").strip()
            if not ref:
                err("E013", "shadow 要写 ref=图元名", cmd)
                continue
            seq += 1
            sp = Prim(kind="shadow", z=layer * 100000 + seq, line=cmd.line, ref=ref)
            sp.dx = P.as_float(kw.get("dx", "0"), "shadow dx", cmd.line, cmd.col)
            sp.dy = P.as_float(kw.get("dy", "0"), "shadow dy", cmd.line, cmd.col)
            sp.alpha = P.as_range(
                P.as_float(kw.get("alpha", "0.25"), "shadow alpha", cmd.line, cmd.col),
                0, 1, "shadow alpha", cmd.line, cmd.col)
            sp.fill = P.as_color(kw.get("color", "#000000"), "shadow color",
                                 cmd.line, cmd.col)
            sp.blur = P.as_range(
                P.as_float(kw.get("blur", "0"), "shadow blur", cmd.line, cmd.col),
                0, 300, "shadow blur", cmd.line, cmd.col)
            refs.append((ref, cmd, "shadow"))
            _tag(sp)
            scene.prims.append(sp)
          except DslError as ex:
            errors.append(ex)
          continue

        if verb == "blur":
          try:
            radius = P.as_range(P.as_float(pos[0], "blur 半径", cmd.line, cmd.col),
                                0.5, 300, "blur 半径", cmd.line, cmd.col)
            alpha = P.as_range(
                P.as_float(kw.get("alpha", "1"), "blur alpha", cmd.line, cmd.col),
                0, 1, "blur alpha", cmd.line, cmd.col)
            blur_seq += 1
            blur_stack.append((blur_seq, radius, alpha))
          except DslError as ex:
            errors.append(ex)
          continue

        if verb == "endblur":
            if not blur_stack:
                err("E006", "endblur 多了（前面没有 blur）", cmd)
                continue
            blur_stack.pop()
            continue

        if verb == "hatch":
          try:
            ref = kw.get("ref", "").strip()
            if not ref:
                err("E013", "hatch 要写 ref=图元名或组名", cmd)
                continue
            seq += 1
            hp = Prim(kind="hatch", z=layer * 100000 + seq, line=cmd.line, ref=ref)
            hp.grad = {
                "angle": P.as_float(kw.get("angle", "45"), "hatch angle", cmd.line, cmd.col),
                "spacing": P.as_range(
                    P.as_float(kw.get("spacing", "18"), "hatch spacing", cmd.line, cmd.col),
                    2, 400, "hatch spacing", cmd.line, cmd.col),
            }
            hp.alpha = P.as_range(
                P.as_float(kw.get("alpha", "1"), "hatch alpha", cmd.line, cmd.col),
                0, 1, "hatch alpha", cmd.line, cmd.col)
            hp.stroke = P.as_color(kw.get("color", "#1f2937"), "hatch color",
                                   cmd.line, cmd.col)
            hp.pen = {
                "width": P.as_range(
                    P.as_float(kw.get("w", "3"), "hatch w", cmd.line, cmd.col),
                    0.3, 40, "hatch w", cmd.line, cmd.col),
                "taper": P.as_range(
                    P.as_float(kw.get("taper", "0.5"), "hatch taper", cmd.line, cmd.col),
                    0, 1, "hatch taper", cmd.line, cmd.col),
                "jitter": P.as_range(
                    P.as_float(kw.get("jitter", "0.6"), "hatch jitter", cmd.line, cmd.col),
                    0, 3, "hatch jitter", cmd.line, cmd.col),
                "roughness": P.as_range(
                    P.as_float(kw.get("rough", "1"), "hatch rough", cmd.line, cmd.col),
                    0.4, 2.5, "hatch rough", cmd.line, cmd.col),
                "wavelength": 48.0, "step": 6.0, "wave": 0.0,
                "overshoot": 0.0, "pin_start": False, "pin_end": False,
            }
            refs.append((ref, cmd, "hatch"))
            _tag(hp, cmd)
            scene.prims.append(hp)
          except DslError as ex:
            errors.append(ex)
          continue

        if verb == "bool":
          try:
            op = kw.get("op", "").strip().lower()
            base = kw.get("base", "").strip()
            other = kw.get("with", "").strip()
            if op not in ("subtract", "union", "intersect"):
                err("E012", f"bool 的 op 只支持 subtract / union / intersect，收到 {op!r}",
                    cmd, cmd.kw_col("op"), len(op))
                continue
            if not base or not other:
                err("E013", "bool 要写 base= 和 with= 两个名字", cmd)
                continue
            seq += 1
            bp = Prim(kind="pathop", z=layer * 100000 + seq, line=cmd.line)
            bp.grad = {"op": op, "base": base, "with": other}
            _fill_common(bp, cmd, cur)
            if "width" in kw:
                bp.width = P.as_float(kw["width"], "bool width", cmd.line,
                                      cmd.kw_col("width"))
            refs.append((base, cmd, "bool"))
            refs.append((other, cmd, "bool"))
            _tag(bp, cmd)
            scene.prims.append(bp)
          except DslError as ex:
            errors.append(ex)
          continue

        if verb == "along":
          try:
            ref = kw.get("ref", "").strip()
            grp = kw.get("group", "").strip()
            if not ref or not grp:
                err("E013", "along 要写 ref=（路径）和 group=（要复制的组）", cmd)
                continue
            seq += 1
            ap = Prim(kind="along", z=layer * 100000 + seq, line=cmd.line)
            ap.grad = {
                "ref": ref, "group": grp,
                "count": int(P.as_range(
                    P.as_float(kw.get("count", "5"), "along count", cmd.line, cmd.col),
                    1, 500, "along count", cmd.line, cmd.col)),
                "scale": P.as_range(
                    P.as_float(kw.get("scale", "1"), "along scale", cmd.line, cmd.col),
                    0.01, 100, "along scale", cmd.line, cmd.col),
                "rot": 1 if P.as_bool(kw.get("rot", "1")) else 0,
            }
            ap.alpha = P.as_range(
                P.as_float(kw.get("alpha", "1"), "along alpha", cmd.line, cmd.col),
                0, 1, "along alpha", cmd.line, cmd.col)
            refs.append((ref, cmd, "along"))
            refs.append((grp, cmd, "along"))
            _tag(ap, cmd)
            scene.prims.append(ap)
          except DslError as ex:
            errors.append(ex)
          continue

        if verb == "use":
            name = pos[0]
            if name not in scene.groups:
                err("E005", f"use 找不到组 {name!r}"
                            + ("（只能复用之前定义过的组）" if name in names else ""),
                    cmd, cmd.col, len(name))
                continue
            m = IDENTITY
            if "flip" in kw:
                f = kw["flip"].strip().lower()
                if f == "x":
                    m = compose((-1, 0, 0, 1, 0, 0), m)
                elif f == "y":
                    m = compose((1, 0, 0, -1, 0, 0), m)
                else:
                    err("E012", f"flip 只能是 x 或 y，收到 {f!r}", cmd,
                        cmd.kw_col("flip"), len(f))
            if "scale" in kw:
                s = P.as_float(kw["scale"], "use scale", cmd.line, cmd.kw_col("scale"))
                P.as_range(s, 0.01, 100, "use scale", cmd.line, cmd.kw_col("scale"))
                m = compose((s, 0, 0, s, 0, 0), m)
            if "rot" in kw:
                deg = P.as_float(kw["rot"], "use rot", cmd.line, cmd.kw_col("rot"))
                r = math.radians(deg)
                m = compose((math.cos(r), math.sin(r), -math.sin(r),
                             math.cos(r), 0, 0), m)
            if "at" in kw:
                x, y = P.as_pair(kw["at"], "use at", cmd.line, cmd.kw_col("at"))
                m = compose((1, 0, 0, 1, x, y), m)
            # 复制前先把"模板里的名字"映射成一套新名字。
            # 不映射的话，克隆品里的 grad ref= / clip / shadow ref= 仍然指向**原模板**，
            # 于是渐变画到原点去了 —— 叶子看着就是一块平色，还不报错。
            remap: dict[str, str] = {}
            for idx in scene.groups[name]:
                src = scene.prims[idx]
                if src.name:
                    remap[src.name] = f"{src.name}#{cmd.line}_{seq}"

            def _fix(ref):
                return remap.get(ref, ref) if isinstance(ref, str) else ref

            for idx in scene.groups[name]:
                src = scene.prims[idx]
                if src.kind == "shadow":
                    continue
                clone = _clone_prim(src, m)
                # use 的产物要能看见：模板组里的图元本来是 invisible 的
                # （不然模板自己会在原点画一份），复制出来必须清掉。
                clone.invisible = False
                seq += 1
                clone.z = layer * 100000 + seq
                clone.line = cmd.line
                if src.name:
                    # _clone_prim 默认把名字清掉（怕抢名），这里要显式给新名字：
                    # 克隆品内部的 grad ref= / clip 得指向**自己这一份**的形状。
                    clone.name = remap[src.name]
                if clone.clip:
                    clone.clip = tuple(_fix(c) for c in clone.clip)
                if clone.grad and clone.grad.get("ref"):
                    old_ref = clone.grad["ref"]
                    clone.grad["ref"] = _fix(old_ref)
                    # 如果参考路径被换成了"克隆品自己的那份"，那它的坐标**已经**
                    # 跟着 use 的矩阵走过了；这时 mate 必须清掉，否则会再平移一次，
                    # 位置正好翻倍（叶子里的侧脉就这么飘出去的）。
                    if old_ref in remap:
                        clone.mate = None
                if clone.ref:
                    clone.ref = _fix(clone.ref)
                _tag(clone)
                scene.prims.append(clone)
            continue

        if verb == "hand":
            if "preset" in kw:
                p = kw["preset"].strip().lower()
                if p not in HAND_PRESETS:
                    err("E012", f"没有这个手感预设 {p!r}（可用："
                                f"{', '.join(HAND_PRESETS)}）", cmd,
                        cmd.kw_col("preset"), len(p))
                else:
                    scene.hand.update(HAND_PRESETS[p])
                    scene.hand["preset"] = p
            for key in ("jitter", "taper", "wave", "wavelength", "step", "seed"):
                if key in kw:
                    scene.hand[key] = P.as_float(kw[key], f"hand {key}", cmd.line,
                                                 cmd.kw_col(key))
            for key in ("rough", "roughness"):
                if key in kw:
                    scene.hand["roughness"] = P.as_float(kw[key], "hand rough",
                                                         cmd.line, cmd.kw_col(key))
            if "width" in kw:
                scene.hand["width"] = P.as_float(kw["width"], "hand width",
                                                 cmd.line, cmd.kw_col("width"))
            continue

        if verb == "layer":
            layer = P.as_float(pos[0], "layer", cmd.line, cmd.col)
            P.as_range(layer, -1000, 1000, "layer", cmd.line, cmd.col)
            continue

        # ---------------- 图元 ----------------
        seq += 1
        z = layer * 100000 + seq
        name = kw.get("name") if "name" in kw else None
        prim = Prim(kind=verb, z=z, name=name, line=cmd.line)
        if name:
            if not P.NAME_RE.match(name):
                err("E004", f"名字只能用字母/数字/下划线/汉字，收到 {name!r}", cmd)
            elif name in names:
                err("E004", f"名字 {name!r} 已经用过了（第 {names[name]} 行）", cmd)
            else:
                names[name] = cmd.line

        try:
            _fill_common(prim, cmd, cur)
            if verb == "rect":
                x = P.as_float(pos[0], "rect x", cmd.line, cmd.col)
                y = P.as_float(pos[1], "rect y", cmd.line, cmd.col)
                w = P.as_float(pos[2], "rect 宽", cmd.line, cmd.col)
                h = P.as_float(pos[3], "rect 高", cmd.line, cmd.col)
                if w <= 0 or h <= 0:
                    raise DslError("E007", f"rect 宽高要大于 0，收到 {w:g}×{h:g}",
                                   cmd.line, cmd.col)
                if "r" in kw:
                    prim.radius = P.as_float(kw["r"], "rect 圆角", cmd.line,
                                             cmd.kw_col("r"))
                    P.as_range(prim.radius, 0, min(w, h) / 2, "rect 圆角",
                               cmd.line, cmd.kw_col("r"))
                    prim.radius *= _scale_of(cur)
                (x0, y0), (x1, y1) = apply(cur, x, y), apply(cur, x + w, y + h)
                prim.rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
            elif verb == "circle":
                cx = P.as_float(pos[0], "circle 圆心 x", cmd.line, cmd.col)
                cy = P.as_float(pos[1], "circle 圆心 y", cmd.line, cmd.col)
                r = P.as_float(pos[2], "circle 半径", cmd.line, cmd.col)
                if r <= 0:
                    raise DslError("E007", f"半径要大于 0，收到 {r:g}", cmd.line, cmd.col)
                cx, cy = apply(cur, cx, cy)
                prim.rect = (cx - r * _scale_of(cur), cy - r * _scale_of(cur),
                             2 * r * _scale_of(cur), 2 * r * _scale_of(cur))
                prim.radius = r * _scale_of(cur)
            elif verb in ("curve", "poly"):
                pts = P.as_points(pos[0], verb, cmd.line, cmd.col)
                prim.closed = P.as_bool(kw.get("closed", "0"))
                if prim.closed and len(pts) < 3:
                    raise DslError("E009", f"closed {verb} 至少 3 个点，收到 {len(pts)}",
                                   cmd.line, cmd.col)
                if len(pts) < 2:
                    raise DslError("E009", f"{verb} 至少 2 个点，收到 {len(pts)}",
                                   cmd.line, cmd.col)
                prim.points = [apply(cur, x, y) for x, y in pts]
                if verb == "poly":
                    prim.smooth = 0.0
                else:
                    prim.smooth = P.as_range(
                        P.as_float(kw.get("smooth", "1"), "smooth", cmd.line,
                                   cmd.kw_col("smooth") if "smooth" in kw else cmd.col),
                        0, 1, "smooth", cmd.line, cmd.col)
                # 带 w= 的曲线/多边形用"笔"来描边：能平滑又能抖
                if "w" in kw:
                    _fill_pen(prim, cmd, _scale_of(cur), scene.hand)
                    if prim.stroke is None:
                        prim.stroke = "#1f2937"
            elif verb == "ink":
                pts = P.as_points(pos[0], "ink", cmd.line, cmd.col)
                if len(pts) < 2:
                    raise DslError("E009", f"ink 至少 2 个点，收到 {len(pts)}",
                                   cmd.line, cmd.col)
                prim.points = [apply(cur, x, y) for x, y in pts]
                prim.closed = P.as_bool(kw.get("closed", "0"))
                _fill_pen(prim, cmd, _scale_of(cur), scene.hand)
            elif verb == "text":
                x = P.as_float(pos[0], "text x", cmd.line, cmd.col)
                y = P.as_float(pos[1], "text y", cmd.line, cmd.col)
                body = pos[2].strip()
                if body.startswith('"') and body.endswith('"') and len(body) >= 2:
                    body = body[1:-1]
                if not body:
                    raise DslError("E013", "text 的正文是空的", cmd.line, cmd.col)
                prim.text = body
                prim.size = P.as_range(
                    P.as_float(pos[3], "text 字号", cmd.line, cmd.col), 1, 400,
                    "text 字号", cmd.line, cmd.col) * _scale_of(cur)
                if "align" in kw:
                    al = kw["align"].strip().lower()
                    if al not in ("left", "center", "right"):
                        raise DslError("E012", f"align 只支持 left/center/right，收到 {al!r}",
                                       cmd.line, cmd.kw_col("align"), len(al))
                    prim.align = al
                if "font" in kw:
                    prim.font = kw["font"].strip().strip('"')
                if "color" in kw:
                    prim.stroke = P.as_color(kw["color"], "color", cmd.line,
                                             cmd.kw_col("color"))
                if "tracking" in kw:
                    prim.tracking = P.as_float(kw["tracking"], "tracking", cmd.line,
                                               cmd.kw_col("tracking"))
                if "hand" in kw:
                    prim.hand = P.as_range(
                        P.as_float(kw["hand"], "hand", cmd.line, cmd.kw_col("hand")),
                        0, 1, "hand", cmd.line, cmd.kw_col("hand"))
                prim.points = [apply(cur, x, y)]
            elif verb == "grad":
                ref_name = (kw.get("ref") or "").strip() or None
                if ref_name:
                    shape = "ref"
                else:
                    if not pos:
                        raise DslError("E002",
                                       "grad 要写形状（rect / circle / poly）或用 ref=",
                                       cmd.line, cmd.col)
                    shape = pos[0].strip().lower()
                if "from" not in kw or "to" not in kw:
                    raise DslError("E013", "grad 要写 from= 和 to= 两个颜色",
                                   cmd.line, cmd.col, 4)
                c0 = P.as_color(kw["from"], "grad from", cmd.line, cmd.kw_col("from"))
                c1 = P.as_color(kw["to"], "grad to", cmd.line, cmd.kw_col("to"))
                ang = P.as_float(kw.get("dir", "90"), "grad dir", cmd.line,
                                 cmd.kw_col("dir"))
                prim.grad = {"from": c0, "to": c1, "dir": ang,
                             "radial": shape == "circle"}
                # 自定义渐变轴：两个点定义方向和长度，不必再靠"角度 + 包围盒"去猜。
                # 弯曲的叶子、斜着的身子，用它颜色才铺得对。
                if "p0" in kw or "p1" in kw:
                    if "p0" not in kw or "p1" not in kw:
                        raise DslError("E013", "自定义轴要 p0= 和 p1= 一起写",
                                       cmd.line, cmd.col)
                    a0 = P.as_points(kw["p0"], "grad p0", cmd.line, cmd.kw_col("p0"))
                    a1 = P.as_points(kw["p1"], "grad p1", cmd.line, cmd.kw_col("p1"))
                    if len(a0) != 1 or len(a1) != 1:
                        raise DslError("E002", "p0 / p1 各要一个点，比如 p0=[100,200]",
                                       cmd.line, cmd.col)
                    prim.grad["p0"] = apply(cur, a0[0][0], a0[0][1])
                    prim.grad["p1"] = apply(cur, a1[0][0], a1[0][1])
                if shape == "ref":
                    prim.grad["ref"] = ref_name
                    if not ref_name.startswith("@"):
                        refs.append((ref_name, cmd, "grad ref"))
                elif shape == "rect":
                    if len(pos) != 5:
                        raise DslError("E002", "grad rect 要 4 个数字（x,y,w,h）",
                                       cmd.line, cmd.col)
                    x, y = P.as_float(pos[1], "grad x", cmd.line, cmd.col), \
                        P.as_float(pos[2], "grad y", cmd.line, cmd.col)
                    w, h = P.as_float(pos[3], "grad 宽", cmd.line, cmd.col), \
                        P.as_float(pos[4], "grad 高", cmd.line, cmd.col)
                    if w <= 0 or h <= 0:
                        raise DslError("E007", "grad rect 宽高要大于 0", cmd.line, cmd.col)
                    (x0, y0), (x1, y1) = apply(cur, x, y), apply(cur, x + w, y + h)
                    prim.rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
                elif shape == "circle":
                    if len(pos) != 4:
                        raise DslError("E002", "grad circle 要 3 个数字（cx,cy,r）",
                                       cmd.line, cmd.col)
                    cx = P.as_float(pos[1], "grad cx", cmd.line, cmd.col)
                    cy = P.as_float(pos[2], "grad cy", cmd.line, cmd.col)
                    r = P.as_float(pos[3], "grad 半径", cmd.line, cmd.col)
                    if r <= 0:
                        raise DslError("E007", "grad 半径要大于 0", cmd.line, cmd.col)
                    cx, cy = apply(cur, cx, cy)
                    s = _scale_of(cur)
                    prim.rect = (cx - r * s, cy - r * s, 2 * r * s, 2 * r * s)
                    prim.radius = r * s
                elif shape == "poly":
                    if len(pos) != 2:
                        raise DslError("E002", "grad poly 要点列", cmd.line, cmd.col)
                    pts = P.as_points(pos[1], "grad poly", cmd.line, cmd.col)
                    if len(pts) < 3:
                        raise DslError("E009", "grad poly 至少 3 个点", cmd.line, cmd.col)
                    prim.points = [apply(cur, x, y) for x, y in pts]
                    prim.closed = True
                else:
                    raise DslError("E012", f"grad 的形状只支持 rect / circle / poly / ref=，"
                                           f"收到 {shape!r}", cmd.line, cmd.col, len(shape))
            elif verb == "ellipse":
                cx = P.as_float(pos[0], "ellipse 中心 x", cmd.line, cmd.col)
                cy = P.as_float(pos[1], "ellipse 中心 y", cmd.line, cmd.col)
                rx = P.as_float(pos[2], "ellipse 横半径", cmd.line, cmd.col)
                ry = P.as_float(pos[3], "ellipse 纵半径", cmd.line, cmd.col)
                if rx <= 0 or ry <= 0:
                    raise DslError("E007", f"椭圆半径要大于 0，收到 {rx:g}×{ry:g}",
                                   cmd.line, cmd.col)
                s = _scale_of(cur)
                cx, cy = apply(cur, cx, cy)
                prim.kind = "circle"          # 画家那边圆和椭圆是同一条路
                prim.rect = (cx - rx * s, cy - ry * s, 2 * rx * s, 2 * ry * s)
                prim.radius = min(rx, ry) * s
            else:                                    # pragma: no cover
                raise DslError("E001", f"没有这个命令 {verb!r}", cmd.line, cmd.col)
            # 几何先解析完，再问"这一笔到底会不会画出东西"。
            # 顺序反了的话，`rect 1,2,3,四` 会先报"没有 fill"，把真正的错盖掉。
            if prim.kind in ("curve", "poly", "rect", "circle") \
                    and prim.fill is None and prim.stroke is None \
                    and not prim.invisible:
                raise DslError("E013",
                               f"{prim.kind} 既没有 fill 也没有 stroke，画不出东西",
                               cmd.line, cmd.col, len(cmd.verb))
        except DslError as ex:
            errors.append(ex)
            continue

        _tag(prim, cmd)
        scene.prims.append(prim)

    if not saw_canvas and not reported_missing_canvas:
        errors.append(DslError("E008", "整个文件没有 canvas 行", 1, 1))
    if clip_stack:
        errors.append(DslError("E006", f"clip {clip_stack[-1]!r} 没有 endclip", 1, 1))
    if blend_stack:
        errors.append(DslError("E006", f"blend {blend_stack[-1]!r} 没有 endblend", 1, 1))
    if blur_stack:
        errors.append(DslError("E006", f"blur 第 {blur_stack[-1][0]} 个没有 endblur", 1, 1))
    # 引用检查放在最后：允许"先用后定义"，但定义必须存在
    known = set(names) | set(scene.groups)
    for ref, cmd, what in refs:
        if ref not in known:
            errors.append(DslError("E005", f"{what} 找不到 {ref!r}", cmd.line,
                                   cmd.col, len(ref)))
    for g in stack:
        errors.append(DslError("E006", f"第 {g.line} 行的 group 没有 endgroup",
                               g.line, 1))
    # along 不能绕成环：组 A 里放一个 along 引用组 A，展开时会无限递归。
    # 以前是静默跳过（画不全还不报错），这里改成明确报错。
    _check_along_cycles(scene, errors)
    if errors:
        raise _Multi(errors)
    scene.group_alpha = dict(gid_alpha)
    scene.meta["prims"] = len(scene.prims)
    return scene


def _check_along_cycles(scene, errors: list[DslError]) -> None:
    """把"组 → 组里的 along 引用的模板组"建成有向图，找环。"""
    edges: dict[str, list[tuple[str, int]]] = {}
    for gname, idxs in scene.groups.items():
        for i in idxs:
            if i >= len(scene.prims):
                continue
            p = scene.prims[i]
            if p.kind != "along":
                continue
            target = p.grad.get("group")
            if target:
                edges.setdefault(gname, []).append((target, p.line))

    WHITE, GREY, BLACK = 0, 1, 2
    color: dict[str, int] = {}

    def walk(node: str, path: list[str]) -> bool:
        state = color.get(node, WHITE)
        if state == GREY:                     # 回到正在走的路径上 → 环
            loop = " → ".join(path[path.index(node):] + [node])
            line = edges.get(path[-1], [(None, 1)])[0][1]
            errors.append(DslError("E019", f"along 套成了环：{loop}", line, 1))
            return True
        if state == BLACK:
            return False
        color[node] = GREY
        for target, line in edges.get(node, []):
            if target not in scene.groups:
                continue
            if target == node:
                errors.append(DslError(
                    "E019", f"along 套成了环：{node} → {node}（组里引用了自己）",
                    line, 1))
                color[node] = BLACK
                return True
            if walk(target, path + [node]):
                color[node] = BLACK
                return True
        color[node] = BLACK
        return False

    for gname in list(scene.groups):
        if color.get(gname, WHITE) == WHITE:
            walk(gname, [])


class _Multi(Exception):
    def __init__(self, errors):
        self.errors = errors
        super().__init__(f"{len(errors)} 个错误")


def _clone_prim(prim: Prim, m) -> Prim:
    """按矩阵克隆一个图元（`use` 用）。只做能做的：点、轴对齐框、半径、字号、笔宽。"""
    import copy

    clone = copy.copy(prim)
    # grad 是 dict，浅拷贝会让所有克隆品**共用同一个**：改一个引用等于改了全家的
    # （五片叶子全指到第一片上，渐变和侧脉就只剩一片有）
    clone.grad = dict(prim.grad) if prim.grad else {}
    clone.points = [apply(m, x, y) for x, y in prim.points]
    # 自定义渐变轴的两个点也要跟着变换，否则渐变轴还留在模板原点附近，
    # 叶子上的渐变就变成一整片平色（看着"没有渐变"）
    if clone.grad.get("p0") is not None:
        clone.grad["p0"] = apply(m, *clone.grad["p0"])
    if clone.grad.get("p1") is not None:
        clone.grad["p1"] = apply(m, *clone.grad["p1"])
    s = _scale_of(m)
    if prim.rect:
        x, y, w, h = prim.rect
        (x0, y0), (x1, y1) = apply(m, x, y), apply(m, x + w, y + h)
        clone.rect = (min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
    if prim.radius:
        clone.radius = prim.radius * s
    clone.size = prim.size * s
    if prim.pen:
        clone.pen = dict(prim.pen)
        clone.pen["width"] = prim.pen.get("width", 3.0) * s
        clone.pen["step"] = prim.pen.get("step", 6.0) * s
    clone.name = None            # 克隆品不抢名字
    clone.clip = prim.clip
    # along 没有几何可变换：位置全靠 ref 路径算，所以把 use 的矩阵带在身上，
    # 上色时用它套一层 painter 变换（否则复制出来的 along 还画在原地）。
    if prim.kind == "along":
        clone.mate = compose(m, prim.mate or IDENTITY)
    elif prim.mate is not None:
        clone.mate = compose(m, prim.mate)
    return clone


def _fill_common(prim: Prim, cmd: P.Command, cur):
    kw = cmd.kw
    none_keys = set()
    for key, attr in (("fill", "fill"), ("stroke", "stroke")):
        if key in kw:
            raw = kw[key].strip().lower()
            if raw in ("none", "transparent", "null"):
                setattr(prim, attr, None)      # 「不要这个」也是要能写出来的
                none_keys.add(key)
            else:
                setattr(prim, attr, P.as_color(kw[key], key, cmd.line, cmd.kw_col(key)))
    if none_keys == {"fill", "stroke"}:
        prim.invisible = True
    keys = ("width", "w")
    for key in keys:
        if key in kw:
            prim.width = P.as_range(
                P.as_float(kw[key], "笔宽", cmd.line, cmd.kw_col(key)), 0, 400,
                "笔宽", cmd.line, cmd.kw_col(key))
            prim.width *= _scale_of(cur)
            break
    if "alpha" in kw:
        prim.alpha = P.as_range(
            P.as_float(kw["alpha"], "alpha", cmd.line, cmd.kw_col("alpha")), 0, 1,
            "alpha", cmd.line, cmd.kw_col("alpha"))


def _fill_pen(prim: Prim, cmd: P.Command, scale: float = 1.0, hand: dict | None = None):
    kw = cmd.kw
    base = dict(DEFAULT_HAND)
    if hand:
        base.update({k: v for k, v in hand.items() if v is not None})
    pen = {
        "width": base["width"] if base.get("width") else 3.0,
        "taper": base["taper"], "jitter": base["jitter"],
        "roughness": base["roughness"], "overshoot": None,
        "wave": base["wave"], "wavelength": base["wavelength"],
        "step": base["step"], "pin_start": False, "pin_end": False,
    }
    if "w" in kw:
        pen["width"] = P.as_range(P.as_float(kw["w"], "w", cmd.line, cmd.kw_col("w")),
                                  0.1, 400, "w", cmd.line, cmd.kw_col("w"))
    pen["width"] *= max(1e-6, scale)
    pen["step"] *= max(1e-6, scale)
    if "taper" in kw:
        pen["taper"] = P.as_range(P.as_float(kw["taper"], "taper", cmd.line,
                                             cmd.kw_col("taper")), 0, 1, "taper",
                                  cmd.line, cmd.kw_col("taper"))
    # 笔压：press=0.4:1:0.7（2~5 个数，沿笔长的宽度倍率）
    # 用冒号分隔：逗号在这个 DSL 里是切词的分隔符，写 press=0.4,1 会被拆成三段。
    if "press" in kw:
        raw_txt = kw["press"].strip().strip('"').strip("'")
        raw = [x.strip() for x in raw_txt.replace(":", ",").split(",") if x.strip()]
        if not 2 <= len(raw) <= 5:
            raise DslError("E012", "press 要写 2~5 个数，用冒号隔开，"
                                   "比如 press=0.4:1:0.7",
                           cmd.line, cmd.kw_col("press"))
        vals = []
        for x in raw:
            vals.append(P.as_range(
                P.as_float(x, "press", cmd.line, cmd.kw_col("press")),
                0.05, 3.0, "press", cmd.line, cmd.kw_col("press")))
        pen["press"] = tuple(vals)
    if "jitter" in kw:
        pen["jitter"] = P.as_range(P.as_float(kw["jitter"], "jitter", cmd.line,
                                              cmd.kw_col("jitter")), 0, 3, "jitter",
                                   cmd.line, cmd.kw_col("jitter"))
    for key in ("rough", "roughness"):
        if key in kw:
            pen["roughness"] = P.as_range(
                P.as_float(kw[key], "rough", cmd.line, cmd.kw_col(key)), 0.4, 2.5,
                "rough", cmd.line, cmd.kw_col(key))
    if "overshoot" in kw:
        pen["overshoot"] = P.as_range(
            P.as_float(kw["overshoot"], "overshoot", cmd.line, cmd.kw_col("overshoot")),
            0, 40, "overshoot", cmd.line, cmd.kw_col("overshoot"))
    if "wave" in kw:
        pen["wave"] = P.as_range(P.as_float(kw["wave"], "wave", cmd.line,
                                            cmd.kw_col("wave")), 0, 2, "wave",
                                 cmd.line, cmd.kw_col("wave"))
    if "wavelength" in kw:
        pen["wavelength"] = P.as_range(
            P.as_float(kw["wavelength"], "wavelength", cmd.line,
                       cmd.kw_col("wavelength")), 0, 2000, "wavelength",
            cmd.line, cmd.kw_col("wavelength"))
    if "step" in kw:
        pen["step"] = P.as_range(
            P.as_float(kw["step"], "step", cmd.line, cmd.kw_col("step")), 1, 100,
            "step", cmd.line, cmd.kw_col("step"))
    # 纹理笔：tex 决定用哪种遮罩，passes>1 就是"干笔多遍"
    tex = kw.get("tex", "").strip().lower()
    if tex and tex != "none":
        if tex not in TEXTURES:
            raise DslError("E012",
                           f"tex 不认识 {tex!r}；可用：{', '.join(TEXTURES)}",
                           cmd.line, cmd.kw_col("tex"), len(tex))
        prim.grad["tex"] = tex
    if "tex_scale" in kw:
        prim.grad["tex_scale"] = P.as_range(
            P.as_float(kw["tex_scale"], "tex_scale", cmd.line, cmd.kw_col("tex_scale")),
            0.1, 12, "tex_scale", cmd.line, cmd.kw_col("tex_scale"))
    if "tex_alpha" in kw:
        prim.grad["tex_alpha"] = P.as_range(
            P.as_float(kw["tex_alpha"], "tex_alpha", cmd.line, cmd.kw_col("tex_alpha")),
            0, 1, "tex_alpha", cmd.line, cmd.kw_col("tex_alpha"))
    if "passes" in kw:
        prim.grad["passes"] = int(P.as_range(
            P.as_float(kw["passes"], "passes", cmd.line, cmd.kw_col("passes")),
            1, 6, "passes", cmd.line, cmd.kw_col("passes")))
    if "spread" in kw:
        prim.grad["spread"] = P.as_range(
            P.as_float(kw["spread"], "spread", cmd.line, cmd.kw_col("spread")),
            0, 2, "spread", cmd.line, cmd.kw_col("spread"))
    if "cap" in kw:
        cap = kw["cap"].strip().lower()
        if cap not in ("round", "flat", "square"):
            raise DslError("E012", f"cap 只能是 round / flat / square，收到 {cap!r}",
                           cmd.line, cmd.kw_col("cap"), len(cap))
        pen["cap"] = cap
    if "pin" in kw:
        p = kw["pin"].strip().lower()
        pen["pin_start"] = p in ("start", "both")
        pen["pin_end"] = p in ("end", "both")
    prim.pen = pen
    # 注意：这里**不能**无条件覆盖 stroke。curve/poly 带 w= 时，
    # 上面已经解析过 stroke= 了；一覆盖，用户写的颜色就静默失效（曾经全部变成深蓝）。
    if "color" in kw:
        prim.stroke = P.as_color(kw["color"], "color", cmd.line, cmd.kw_col("color"))
    elif prim.stroke is None:
        prim.stroke = "#1f2937"
