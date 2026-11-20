"""语法：一行 → 一条命令。表驱动，参数个数和属性名在这里就卡掉。"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field

from .errors import DslError
from .lexer import Token


@dataclass
class Spec:
    pos_min: int
    pos_max: int
    keys: tuple[str, ...]
    required: tuple[str, ...] = ()


VERBS: dict[str, Spec] = {
    "canvas":    Spec(1, 1, ()),
    "bg":        Spec(1, 1, ()),
    "rect":      Spec(4, 4, ("fill", "stroke", "width", "r", "alpha", "name")),
    "circle":    Spec(3, 3, ("fill", "stroke", "width", "alpha", "name")),
    "ellipse":   Spec(4, 4, ("fill", "stroke", "width", "alpha", "name")),
    "curve":     Spec(1, 1, ("fill", "stroke", "width", "closed", "smooth",
                             "alpha", "name", "w", "taper", "press", "jitter", "rough",
                             "roughness", "overshoot", "wave", "wavelength", "step",
                             "tex", "tex_scale", "tex_alpha", "passes", "spread", "cap")),
    "poly":      Spec(1, 1, ("fill", "stroke", "width", "closed", "alpha", "name",
                             "w", "taper", "press", "jitter", "rough", "roughness",
                             "overshoot", "wave", "wavelength", "step",
                             "tex", "tex_scale", "tex_alpha", "passes", "spread", "cap")),
    "ink":       Spec(1, 1, ("w", "color", "alpha", "taper", "press", "jitter", "rough",
                             "roughness", "overshoot", "closed", "pin", "wave",
                             "wavelength", "step", "name", "tex", "tex_scale",
                             "tex_alpha", "passes", "spread", "cap")),
    "text":      Spec(4, 4, ("size", "color", "align", "font", "hand", "tracking",
                             "name")),
    "group":     Spec(0, 1, ("name", "at", "rot", "scale", "flip", "about",
                             "template", "alpha")),
    "endgroup":  Spec(0, 0, ()),
    "layer":     Spec(1, 1, ()),
    "clip":      Spec(1, 1, ()),
    "endclip":   Spec(0, 0, ()),
    "blend":     Spec(1, 1, ()),
    "endblend":  Spec(0, 0, ()),
    "shadow":    Spec(0, 0, ("ref", "dx", "dy", "alpha", "color", "blur")),
    "blur":      Spec(1, 1, ("alpha",)),
    "endblur":   Spec(0, 0, ()),
    "use":       Spec(1, 1, ("at", "scale", "rot", "flip")),
    "grad":      Spec(0, 6, ("from", "to", "dir", "alpha", "name", "r",
                             "ref", "p0", "p1")),
    "hatch":     Spec(0, 0, ("ref", "angle", "spacing", "w", "color", "alpha",
                             "jitter", "taper", "rough", "name")),
    "bool":      Spec(0, 0, ("op", "base", "with", "fill", "stroke", "width",
                             "alpha", "name")),
    "along":     Spec(0, 0, ("ref", "group", "count", "scale", "rot", "alpha", "name")),
    "hand":      Spec(0, 0, ("preset", "jitter", "taper", "rough", "roughness",
                             "wave", "wavelength", "width", "seed", "step")),
}

# 可以"裸写"的开关：`curve [...] closed` 等价于 `closed=1`
FLAGS = {"closed"}

COLOR_RE = re.compile(r"^#([0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
NAME_RE = re.compile(r"^[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff\-]*$")


@dataclass
class Command:
    verb: str
    pos: list[str]
    kw: dict[str, str]
    line: int
    col: int
    raw: str = ""
    tokens: list[Token] = field(default_factory=list)

    def kw_col(self, key: str) -> int:
        for t in self.tokens:
            if t.text.startswith(key + "="):
                return t.col
        return self.col


def parse_command(tokens: list[Token], line: int, raw: str) -> Command:
    if not tokens:
        raise DslError("E001", "空行不该走到这里", line, 1)
    head = tokens[0]
    verb = head.text.lower()
    spec = VERBS.get(verb)
    if spec is None:
        hint = ""
        if "=" in head.text:
            hint = "（这一行看着像上一行的续行：上一行结尾少了 \\ 吗？）"
        raise DslError("E001", f"没有这个命令 {head.text!r}{hint}", line, head.col,
                       len(head.text))

    pos: list[str] = []
    kw: dict[str, str] = {}
    kw_tokens: list[Token] = [head]
    for tok in tokens[1:]:
        text = tok.text
        low = text.strip().lower()
        if "=" not in text and low in FLAGS and low in spec.keys:
            kw[low] = "1"
            kw_tokens.append(tok)
            continue
        if "=" in text and not text.startswith('"'):
            key, _, value = text.partition("=")
            key = key.strip().lower()
            if key not in spec.keys:
                raise DslError("E011", f"{verb} 没有 {key!r} 这个属性"
                                       f"（可用：{', '.join(spec.keys) or '无'}）",
                               line, tok.col, len(key))
            if key in kw:
                raise DslError("E015", f"属性 {key!r} 写了两次", line, tok.col, len(key))
            if not value.strip():
                raise DslError("E013", f"属性 {key!r} 没有值", line, tok.col, len(key))
            kw[key] = value.strip()
            kw_tokens.append(tok)
        else:
            pos.append(text)
            kw_tokens.append(tok)

    if not (spec.pos_min <= len(pos) <= spec.pos_max):
        want = (f"{spec.pos_min}" if spec.pos_min == spec.pos_max
                else f"{spec.pos_min}~{spec.pos_max}")
        raise DslError("E002", f"{verb} 要 {want} 个位置参数，收到 {len(pos)} 个",
                       line, head.col, len(head.text))
    for key in spec.required:
        if key not in kw:
            raise DslError("E013", f"{verb} 缺必填属性 {key!r}", line, head.col,
                           len(head.text))
    return Command(verb, pos, kw, line, head.col, raw, kw_tokens)


# --------------------------------------------------------------------------- #
# 值解析（resolve 和 parser 共用；失败一律抛 E012/E003/E007）
# --------------------------------------------------------------------------- #

def as_float(text: str, what: str, line: int, col: int) -> float:
    t = text.strip()
    try:
        v = float(t)
    except ValueError:
        raise DslError("E012", f"{what} 要是数字，收到 {t!r}", line, col, len(t))
    if not math.isfinite(v):
        raise DslError("E012", f"{what} 不是有限数：{t!r}", line, col, len(t))
    return v


def as_int(text: str, what: str, line: int, col: int) -> int:
    v = as_float(text, what, line, col)
    if abs(v - round(v)) > 1e-9:
        raise DslError("E012", f"{what} 要是整数，收到 {text!r}", line, col, len(text))
    return int(round(v))


def as_pair(text: str, what: str, line: int, col: int) -> tuple[float, float]:
    t = text.strip()
    if t.startswith("[") and t.endswith("]"):
        t = t[1:-1]
    parts = [x for x in re.split(r"[,\s]+", t) if x]
    if len(parts) != 2:
        raise DslError("E012", f"{what} 要写成 [x,y]，收到 {text!r}", line, col, len(text))
    return (as_float(parts[0], what + " 的 x", line, col),
            as_float(parts[1], what + " 的 y", line, col))


def as_points(text: str, what: str, line: int, col: int) -> list[tuple[float, float]]:
    t = text.strip()
    if not (t.startswith("[") and t.endswith("]")):
        raise DslError("E012", f"{what} 的点列要写在方括号里，收到 {t[:30]!r}",
                       line, col, len(t))
    nums = [x for x in re.split(r"[,\s]+", t[1:-1].strip()) if x]
    if not nums:
        raise DslError("E009", f"{what} 的点列是空的", line, col, len(t))
    vals = [as_float(x, what + " 的点", line, col) for x in nums]
    if len(vals) % 2:
        raise DslError("E012", f"{what} 的点列要 x,y 成对，收到 {len(vals)} 个数",
                       line, col, len(t))
    return list(zip(vals[0::2], vals[1::2]))


def as_color(text: str, what: str, line: int, col: int) -> str:
    t = text.strip()
    if not COLOR_RE.match(t):
        raise DslError("E003", f"{what} 要写 #RGB / #RRGGBB / #RRGGBBAA，收到 {t!r}",
                       line, col, len(t))
    return t.lower()


def as_range(value: float, lo: float, hi: float, what: str,
             line: int, col: int) -> float:
    if not (lo <= value <= hi):
        raise DslError("E007", f"{what} 要在 {lo:g}~{hi:g} 之间，收到 {value:g}",
                       line, col, 1)
    return value


def as_bool(text: str) -> bool:
    return text.strip().lower() not in ("0", "false", "no", "off", "")
