"""预处理：`include` 文件、`let` 变量、`def` 宏。

三样都做在**命令层**：展开发生在词法切分之后、语法解析之前，
所以行号永远是调用点（或 include 那一行）的行号 —— 报错指向"你写的哪一行"，
而不是库文件里那一行。

为什么不是"文本级宏"：文本级展开会把行号搞乱，也会把 `$` 伸进不该伸的地方
（比如字符串里恰好有个美元符号）。命令级只认 `$名字` 这种形式，边界清楚。

语法：

    include "lib/orange.fyb"      # 相对当前文件；里面的 let / def 会并进来
    let 主色 = #C0392B            # 值可以是颜色/数字/坐标/点列
    let 半径 = $边长 * 0.5        # 纯数字表达式会算出来
    def 气孔 (x, y, r)
      circle $x,$y,$r fill=#A8130A alpha=0.22
    enddef
    气孔 300,470,7                # 调用：按位置传参

`$$` 表示一个字面的 `$`。
"""
from __future__ import annotations

import re
from pathlib import Path

from .errors import DslError
from .lexer import split_source, tokenize
from .parser import VERBS

IDENT = r"[A-Za-z_\u4e00-\u9fff][\w\u4e00-\u9fff\-]*"
VAR_RE = re.compile(r"\$(" + IDENT + r")")
LET_RE = re.compile(r"^let\s+(" + IDENT + r")\s*=\s*(.+)$")
DEF_RE = re.compile(r"^def\s+(" + IDENT + r")\s*(?:\((.*)\))?\s*$")
INCLUDE_RE = re.compile(r'^include\s+"([^"]+)"\s*$')
NUM_EXPR_RE = re.compile(r"^[\d\s+\-*/().]+$")
MAX_DEPTH = 12          # 宏展开深度
MAX_INCLUDE = 8         # include 嵌套深度


class _Def:
    __slots__ = ("name", "params", "body", "line")

    def __init__(self, name: str, params: list[str],
                 body: list[tuple[int, str]], line: int):
        self.name = name
        self.params = params
        self.body = body
        self.line = line


def _apply(text: str, mapping: dict[str, str]) -> str:
    """把 $名字 换成值；没定义的保持原样，交给后面查。"""
    return VAR_RE.sub(lambda m: mapping.get(m.group(1), m.group(0)), text)


def _eval_num(text: str) -> str | None:
    """纯数字表达式算一个值；不是数字就返回 None（当字符串用）。

    只放行 数字 / 空格 / + - * / ( ) . 这些字符，并用空内建环境求值。
    """
    t = text.strip()
    if not t or not NUM_EXPR_RE.match(t) or not re.search(r"\d", t):
        return None
    try:
        v = eval(t, {"__builtins__": {}}, {})      # noqa: S307 - 字符白名单 + 无内建
    except Exception:                              # noqa: BLE001
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        return None
    if v != v or v in (float("inf"), float("-inf")):
        return None
    if abs(v - round(v)) < 1e-9:
        return str(int(round(v)))
    return f"{v:.6f}".rstrip("0").rstrip(".")


def _undefined(text: str) -> str | None:
    m = VAR_RE.search(text)
    return m.group(1) if m else None


def expand(lines: list[tuple[int, str]],
           base_dir: Path | None = None) -> tuple[list[tuple[int, str]], list[DslError]]:
    """返回 (展开后的逻辑行, 错误)。lines 形如 [(行号, 文字)]。"""
    errors: list[DslError] = []
    env: dict[str, str] = {}
    defs: dict[str, _Def] = {}
    body: list[tuple[int, str]] = []
    open_files: list[Path] = []

    def _load(rel: str, src_dir: Path | None, line_no: int):
        raw = rel.strip()
        p = Path(raw)
        if not p.is_absolute():
            p = (src_dir or base_dir or Path.cwd()) / raw
        try:
            p = p.resolve()
        except OSError:
            pass
        if p in open_files:
            errors.append(DslError("E018", f"include 绕回来了：{p.name} 正在被包含",
                                   line_no, 1))
            return None
        if not p.is_file():
            errors.append(DslError("E018", f"include 找不到文件：{p}", line_no, 1))
            return None
        try:
            text = p.read_text(encoding="utf-8-sig")
        except OSError as ex:
            errors.append(DslError("E018", f"include 读不了：{ex}", line_no, 1))
            return None
        return p, split_source(text)

    def process(src: list[tuple[int, str]], src_dir: Path | None,
                depth: int, override: int | None = None) -> None:
        i, n = 0, len(src)
        while i < n:
            no, text = src[i]
            if override is not None:
                no = override          # include 进来的行，报错指向 include 那一行
            s = text.strip()

            # ── include ────────────────────────────────
            m = INCLUDE_RE.match(s)
            if m:
                if depth >= MAX_INCLUDE:
                    errors.append(DslError("E018", f"include 嵌太深了（上限 {MAX_INCLUDE}）",
                                           no, 1))
                else:
                    got = _load(m.group(1), src_dir, no)
                    if got:
                        p, sub = got
                        open_files.append(p)
                        process(sub, p.parent, depth + 1, override=no)
                        open_files.pop()
                i += 1
                continue

            # ── let ────────────────────────────────────
            m = LET_RE.match(s)
            if m:
                name, raw = m.group(1), m.group(2).strip()
                val = _apply(raw.replace("$$", "\x00"), env).replace("\x00", "$")
                bad = _undefined(val)
                if bad:
                    errors.append(DslError(
                        "E017", f"变量 ${bad} 还没定义（let {name} 用到了它）", no, 1))
                else:
                    val = _eval_num(val) or val
                    if name in defs:
                        errors.append(DslError(
                            "E014", f"{name} 已经是个宏了，不能同名再当变量", no, 1))
                    else:
                        env[name] = val
                i += 1
                continue

            # ── def ────────────────────────────────────
            m = DEF_RE.match(s)
            if m:
                name = m.group(1)
                params = [p.strip() for p in (m.group(2) or "").replace(" ", ",").split(",")]
                params = [p for p in params if p]
                bad_param = next((p for p in params if not re.fullmatch(IDENT, p)), None)
                if bad_param:
                    errors.append(DslError("E004", f"宏参数名不合法：{bad_param!r}", no, 1))
                j = i + 1
                collected: list[tuple[int, str]] = []
                closed = False
                while j < n:
                    btext = src[j][1].strip()
                    if btext == "enddef":
                        closed = True
                        j += 1
                        break
                    if DEF_RE.match(btext):
                        errors.append(DslError("E016", "宏里不能再定义宏（先 enddef）",
                                               no if override is not None else src[j][0], 1))
                        closed = True
                        j += 1
                        break
                    # 和普通行一样先把 $$ 转义掉，否则宏体里的 $$ 会被当成两个字面 $
                    collected.append((src[j][0], src[j][1].replace("$$", "\x00")))
                    j += 1
                if not closed:
                    errors.append(DslError("E016", f"def {name} 没有 enddef", no, 1))
                elif name in defs:
                    errors.append(DslError(
                        "E014", f"宏 {name} 已经定义过（第 {defs[name].line} 行）", no, 1))
                elif name in VERBS:
                    errors.append(DslError("E014", f"宏不能用命令名 {name!r} 当名字", no, 1))
                elif name in env:
                    errors.append(DslError("E014", f"{name} 已经是变量名了，宏不能用同名",
                                           no, 1))
                elif not bad_param:
                    defs[name] = _Def(name, params, collected, no)
                i = j
                continue

            if s == "enddef":
                errors.append(DslError("E016", "enddef 多了（前面没有 def）", no, 1))
                i += 1
                continue

            replaced = text.replace("$$", "\x00")
            body.append((no, replaced))
            i += 1

    process(lines, base_dir, 0)

    # ── 变量替换：放在收集完所有 let 之后做 ────────────────────
    # 语义是"位置无关"：文件里哪一行写的 let，全文件都认。
    # 这样才敢说"改一处，全场跟着变"；否则同一行在宏里和在正文里取值不一致。
    resolved: list[tuple[int, str]] = []
    for no, text in body:
        line = _apply(text, env).replace("\x00", "$")
        bad = _undefined(line)
        if bad:
            # 整行丢掉：否则下游还会为 "$没这个" 再报一次"颜色不合法"，
            # 一个错报两遍，反而看不清真正的病因
            errors.append(DslError("E017", f"变量 ${bad} 没有定义", no, 1))
        else:
            resolved.append((no, line))

    # ── 展开宏调用（可能嵌套，带深度上限）─────────────────────
    if not defs:
        return resolved, errors

    out: list[tuple[int, str]] = []
    for no, text in resolved:
        out.extend(_expand_line(no, text, env, defs, 0, errors))
    return out, errors


def _expand_line(no: int, text: str, env: dict[str, str], defs: dict[str, _Def],
                 depth: int, errors: list[DslError]) -> list[tuple[int, str]]:
    toks = tokenize(text)
    if not toks:
        return [(no, text)]
    head = toks[0].text
    d = defs.get(head)
    if d is None:
        return [(no, text)]                 # 不是宏调用，原样返回
    if depth > MAX_DEPTH:
        errors.append(DslError("E016", f"宏 {head} 展开太深（是不是在调自己？）", no, 1))
        return []
    args = [t.text for t in toks[1:]]
    if len(args) != len(d.params):
        errors.append(DslError(
            "E014", f"宏 {head} 要 {len(d.params)} 个参数"
                    f"（{', '.join(d.params) or '无'}），收到 {len(args)} 个", no, 1))
        return []
    mapping = dict(zip(d.params, args))
    out: list[tuple[int, str]] = []
    for _bno, btext in d.body:
        line = _apply(btext, {**env, **mapping}).replace("\x00", "$")
        bad = _undefined(line)
        if bad:
            errors.append(DslError("E017", f"宏 {head} 里用到了没定义的 ${bad}", no, 1))
            continue
        out.extend(_expand_line(no, line, env, defs, depth + 1, errors))
    return out
