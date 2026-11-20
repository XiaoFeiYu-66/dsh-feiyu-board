"""裁剪的回归测试。跑法：python tests/run_clip.py

重点是**嵌套 clip 要求交**：只取最内层的话，外层被静默丢掉，
画出来是错的但不报错（这类"不吭声的错"最危险）。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.compiler import compile_text          # noqa: E402
from fyb.painter import render                 # noqa: E402

fails: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


def px(src, x, y):
    r = compile_text(src)
    assert r.ok, [(e.code, e.line) for e in r.errors]
    cv = render(r.scene, scale=1)
    c = cv.img.pixelColor(x, y)
    return (c.red(), c.green(), c.blue())


RED, WHITE = (255, 0, 0), (255, 255, 255)
C = "canvas 200x200\nbg #ffffff\n"

# 单层 clip：左半裁剪
src = (C + "rect 0,0,100,200 fill=none stroke=none name=a\n"
           "clip a\nrect 0,0,200,200 fill=#ff0000\nendclip\n")
check("单层 clip 生效", px(src, 50, 100) == RED, f"{px(src, 50, 100)}")
check("单层 clip 之外是白的", px(src, 150, 100) == WHITE, f"{px(src, 150, 100)}")

# 嵌套 clip：a=左半，b=上半 → 只剩左上
src = (C + "rect 0,0,100,200 fill=none stroke=none name=a\n"
           "rect 0,0,200,100 fill=none stroke=none name=b\n"
           "clip a\nclip b\nrect 0,0,200,200 fill=#ff0000\nendclip\nendclip\n")
check("嵌套 clip 求交（左上）", px(src, 50, 50) == RED, f"{px(src, 50, 50)}")
check("嵌套 clip 求交（右上不行）", px(src, 150, 50) == WHITE, f"{px(src, 150, 50)}")
check("嵌套 clip 求交（左下不行）", px(src, 50, 150) == WHITE, f"{px(src, 50, 150)}")

# clip 之后要恢复
src = (C + "rect 0,0,100,200 fill=none stroke=none name=a\n"
           "clip a\nrect 0,0,200,200 fill=#ff0000\nendclip\n"
           "rect 120,120,80,80 fill=#00ff00\n")
check("走出 clip 后不再被裁", px(src, 180, 180) == (0, 255, 0), f"{px(src, 180, 180)}")

# 裁剪引用了组（组内所有形状求并）
src = (C + "group name=g\nrect 0,0,60,60 fill=none stroke=none\n"
           "rect 140,140,60,60 fill=none stroke=none\nendgroup\n"
           "clip g\nrect 0,0,200,200 fill=#ff0000\nendclip\n")
check("clip 组：组内左上", px(src, 30, 30) == RED, f"{px(src, 30, 30)}")
check("clip 组：中间不该有", px(src, 100, 100) == WHITE, f"{px(src, 100, 100)}")
check("clip 组：组内右下", px(src, 170, 170) == RED, f"{px(src, 170, 170)}")

# 同一段 clip 里的**第二笔**也要被裁。
# 每个图元单独走一遍 painter，画完会 setClipping(False)；
# 如果状态字典没跟着清，第二笔就会以为"已经裁好了"直接画出去 ——
# 橙子外面那圈红晕就是这么来的。
src = (C + "circle 100,100,50 fill=#cccccc name=body\n"
           "clip body\n"
           "grad rect 50,50,100,100 from=#ff0000 to=#ff0000 dir=90\n"
           "grad circle 100,150,60 from=#00ff00AA to=#00ff0000\n"
           "endclip\n")
check("clip 里第二笔也被裁", px(src, 100, 165) == WHITE, f"{px(src, 100, 165)}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
