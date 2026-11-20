"""随机数：与 dsh-scribble 的 mulberry32 逐位对齐。

对照移植时这非常重要——只要有一处取值顺序不同，抖动就全错位，
像素对照也就失去意义。
"""
from __future__ import annotations


class Rng:
    def __init__(self, seed: int):
        self._a = int(seed) & 0xFFFFFFFF

    def next(self) -> float:
        a = (self._a + 0x6D2B79F5) & 0xFFFFFFFF
        self._a = a
        t = a
        t = _imul(t ^ (t >> 15), 1 | t) & 0xFFFFFFFF
        t = (t + _imul(t ^ (t >> 7), 61 | t)) & 0xFFFFFFFF ^ t
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296.0

    # 便捷方法（与 JS 的 rng 接口同名，方便对照）
    def range(self, lo, hi):
        return lo + (hi - lo) * self.next()

    def sign(self):
        return -1 if self.next() < 0.5 else 1


def _imul(a: int, b: int) -> int:
    """JS Math.imul 的 32 位有符号乘法。"""
    return ((a & 0xFFFFFFFF) * (b & 0xFFFFFFFF)) & 0xFFFFFFFF


def seed_hash(*parts) -> int:
    """把若干片段稳定地散成一个种子（FNV-1a）。

    为什么不用 Python 的 hash()：它对字符串每进程随机化，同一个文件
    两次运行会画出不同的抖 —— 那就没法对比了。
    """
    h = 2166136261
    for part in parts:
        for ch in str(part):
            h ^= ord(ch)
            h = _imul(h, 16777619)
    return h & 0xFFFFFFFF
