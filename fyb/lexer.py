"""词法：把一行切成 token，并记住每个 token 的列号（报错要用）。

切分规则（刻意简单，因为要能被写、被 diff、被肉眼数）：
- 逗号在方括号和引号之外时是分隔符；
- 方括号里保持原样（点列），引号里保持原样（文字）；
- `#` 开头的整行是注释（行内不认注释——颜色就是 `#`，不能歧义）；
- 行尾反斜杠表示续行。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Token:
    text: str
    col: int          # 1-based，指向该 token 的第一个字符


def strip_comment(line: str) -> str:
    if line.lstrip().startswith("#"):
        return ""
    return line


def tokenize(line: str) -> list[Token]:
    out: list[Token] = []
    buf: list[str] = []
    start = -1
    depth = 0
    quote = False
    i = 0
    n = len(line)

    def flush():
        nonlocal buf, start
        if buf:
            text = "".join(buf).strip()
            if text:
                out.append(Token(text, (start + 1) if start >= 0 else 1))
        buf = []
        start = -1

    while i < n:
        ch = line[i]
        if quote:
            buf.append(ch)
            if ch == '"' and (i == 0 or line[i - 1] != "\\"):
                quote = False
            i += 1
            continue
        if ch == '"':
            if start < 0:
                start = i
            quote = True
            buf.append(ch)
            i += 1
            continue
        if depth > 0:
            buf.append(ch)
            if ch == "[":
                depth += 1
            elif ch == "]":
                depth -= 1
            i += 1
            continue
        if ch == "[":
            if start < 0:
                start = i
            depth = 1
            buf.append(ch)
            i += 1
            continue
        if ch == ",":
            flush()
            i += 1
            continue
        if ch.isspace():
            if buf:
                flush()
            i += 1
            continue
        if start < 0:
            start = i
        buf.append(ch)
        i += 1
    flush()
    return out


def split_source(text: str) -> list[tuple[int, str]]:
    """按物理行切，处理 `\\` 续行；返回 [(行号, 拼好的逻辑行)]。"""
    out = []
    buf = ""
    buf_line = 0
    for no, raw in enumerate(text.splitlines(), 1):
        stripped = strip_comment(raw)
        if not stripped.strip():
            # 空行和注释行：续行中途遇到要跳过，否则会把点列切断
            continue
        if not buf:
            buf_line = no
        body = stripped.rstrip()
        if body.endswith("\\"):
            buf += body[:-1] + " "
            continue
        buf += body
        out.append((buf_line, buf))
        buf = ""
    if buf.strip():
        out.append((buf_line or 1, buf))     # 悬空续行：由 parser 报 E010
    return out
