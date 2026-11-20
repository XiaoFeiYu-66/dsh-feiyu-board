"""编译入口：文本 → 场景。所有错误收集成一份再抛。"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .errors import DslError
from .expand import expand
from .ir import Scene
from .lexer import split_source, tokenize
from .parser import Command, parse_command
from .resolve import _Multi, build


@dataclass
class Result:
    scene: Scene | None = None
    errors: list[DslError] = field(default_factory=list)
    commands: list[Command] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors and self.scene is not None


def compile_text(text: str, base_dir=None) -> Result:
    res = Result()
    text = text.lstrip("\ufeff")          # Windows 工具写出来的 BOM，不是语法
    raw = text.splitlines()
    for no in range(len(raw) - 1, -1, -1):
        if raw[no].strip():
            if raw[no].rstrip().endswith("\\"):
                res.errors.append(DslError("E010", "续行符 \\ 后面没有内容了",
                                           no + 1, len(raw[no])))
            break
    if res.errors:
        return res
    lines = split_source(text)
    # include / let / def 在这一层展开：行号沿用调用点，报错才指得回人写的那一行
    lines, expand_errors = expand(lines, base_dir)
    res.errors.extend(expand_errors)
    for no, logical in lines:
        if not logical.strip():
            continue
        try:
            res.commands.append(parse_command(tokenize(logical), no, logical))
        except DslError as ex:
            res.errors.append(ex)
    # 语法错也继续走一遍 resolve：两遍的错误一起给，别让人改一轮跑一轮。
    if res.commands:
        try:
            res.scene = build(res.commands, lines)
        except _Multi as ex:
            res.errors.extend(ex.errors)
            res.scene = None
    res.errors.sort(key=lambda e: (e.line, e.col, e.code))
    return res


def compile_file(path: str) -> Result:
    with open(path, "r", encoding="utf-8-sig") as f:
        return compile_text(f.read(), Path(path).resolve().parent)
