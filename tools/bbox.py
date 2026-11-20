"""量场景墨迹的包围盒，用来精确定位（不靠猜）。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from fyb.compiler import compile_file
from fyb.painter import render
from fyb.balance import image_to_array

name = sys.argv[1] if len(sys.argv) > 1 else "branch-full"
r = compile_file(str(ROOT / "scenes" / f"{name}.fyb"))
cv = render(r.scene, scale=1)
a = image_to_array(cv.img).astype(np.int16)
bg = (a[1, 1]).astype(np.int16)
ink = np.abs(a - bg).max(axis=2) > 10
ys, xs = np.nonzero(ink)
h, w = ink.shape
print("画布 %dx%d" % (w, h))
print("墨迹 x %d..%d (宽 %d)  y %d..%d (高 %d)"
      % (xs.min(), xs.max(), xs.max() - xs.min(),
         ys.min(), ys.max(), ys.max() - ys.min()))
print("左边距 %d  右边距 %d  上边距 %d  下边距 %d"
      % (xs.min(), w - 1 - xs.max(), ys.min(), h - 1 - ys.max()))
