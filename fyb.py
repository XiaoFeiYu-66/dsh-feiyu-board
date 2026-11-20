#!/usr/bin/env python
"""小飞鱼画板的启动器。

为什么需要它：`python -m fyb` 只有在包目录里才能跑（Python 从当前目录找模块），
换个工作目录就 "No module named fyb"。这个脚本把自己的目录塞进 sys.path，
所以**在任何目录**下都能用：

    python C:\\某个地方\\feiyu-board\\fyb.py render D:\\画\\a.fyb --out D:\\画\\a.png

也可以把这一整个目录加到 PATH，然后直接 `fyb.py`（Windows 上关联到 python）。
"""
from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from fyb.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
