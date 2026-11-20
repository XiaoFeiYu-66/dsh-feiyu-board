"""错误码与报错格式。

设计原则：**一次报全，带行号和列号，带上下文和插入符**。
看不见屏幕的人（我）只能靠这段文本定位，所以它必须是可读的，
而不是一句 "syntax error"。
"""
from __future__ import annotations

CODES = {
    "E001": "未知命令",
    "E002": "参数个数不对",
    "E003": "颜色格式不对",
    "E004": "名字重复",
    "E005": "引用不存在",
    "E006": "组没有配平",
    "E007": "数值越界",
    "E008": "第一行必须是 canvas",
    "E009": "闭合图形点数不足",
    "E010": "续行悬空",
    "E011": "不认识这个属性",
    "E012": "数字写错了",
    "E013": "缺必填属性",
    "E014": "属性冲突",
    "E015": "同一行里同一属性写了两遍",
}


class DslError(Exception):
    def __init__(self, code: str, message: str, line: int = 0,
                 col: int = 0, length: int = 1):
        super().__init__(message)
        self.code = code
        self.message = message
        self.line = line
        self.col = col
        self.length = max(1, length)

    @property
    def title(self) -> str:
        return CODES.get(self.code, "错误")

    def render(self, source: str, path: str = "<scene>") -> str:
        lines = source.splitlines()
        head = f"{path}:{self.line}:{self.col}  {self.code}  {self.title}：{self.message}"
        if not (1 <= self.line <= len(lines)):
            return head
        text = lines[self.line - 1]
        gutter = f"{self.line:>4} | "
        caret = " " * (len(gutter) + max(0, self.col - 1)) + "^" * self.length
        return "\n".join([head, gutter + text, caret])


def format_all(errors: list[DslError], source: str, path: str) -> str:
    errors = sorted(errors, key=lambda e: (e.line, e.col, e.code))
    blocks = [e.render(source, path) for e in errors]
    n = len(errors)
    return "\n\n".join(blocks) + f"\n\n{n} 个错误"
