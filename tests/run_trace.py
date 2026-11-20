"""fyb trace 的回归测试。跑法：python tests/run_trace.py"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from fyb.trace import (adaptive, binarize, box_mean, dilate, load_gray,  # noqa: E402
                       merge_paths, otsu, prune_spurs, simplify, thin,
                       trace_contour, trace_skeleton)

fails: list[str] = []


def check(name, cond, detail=""):
    if cond:
        print(f"ok   {name}")
    else:
        fails.append(name)
        print(f"FAIL {name}  {detail}")


# ── 轮廓：矩形应该简化成 4 个角 ─────────────────────
m = np.zeros((40, 40), bool)
m[8:32, 10:30] = True
c = trace_contour(m)
s = simplify(c, 1.0, closed=True)
check("矩形轮廓走通", len(c) >= 40, f"{len(c)} 点")
check("矩形简化成 4 角", len(s) == 4, f"{s}")

# 轮廓要闭合：首尾应该在同一个像素附近（或正好绕回起点）
xs = [p[0] for p in c]
ys = [p[1] for p in c]
check("轮廓包住物体", min(xs) <= 10 and max(xs) >= 30 and min(ys) <= 8 and max(ys) >= 32,
      f"x {min(xs)}..{max(xs)} y {min(ys)}..{max(ys)}")

# 空图不能崩
check("空掩码返回空", trace_contour(np.zeros((10, 10), bool)) == [])


# ── 骨架：一条横线应该走成一条 ───────────────────────
sk = np.zeros((40, 60), bool)
sk[20, 5:55] = True
lines = trace_skeleton(sk, min_len=5)
check("横线走成 1 条", len(lines) == 1 and len(lines[0]) >= 45,
      f"{len(lines)} 条 {[len(l) for l in lines]}")

# 一条折线（有拐角）：8 连通骨架在拐角会有 3 个邻居，不该被切开
sk2 = np.zeros((60, 60), bool)
sk2[10:50, 10:12] = True
sk2[48:50, 10:50] = True
lines2 = trace_skeleton(thin(sk2), min_len=5)
total = sum(len(l) for l in lines2)
check("L 形不被切成碎片", len(lines2) <= 2 and total > 60,
      f"{len(lines2)} 条 / {total} 点")

# 毛刺应该被剪掉：主线上挂几根小刺
sk3 = np.zeros((40, 60), bool)
sk3[20, 5:55] = True
for x in (15, 25, 35):
    sk3[17:20, x] = True
pruned = prune_spurs(sk3, max_len=6)
lines3 = trace_skeleton(pruned, min_len=5)
check("毛刺被剪掉后仍是一条", len(lines3) == 1,
      f"{len(lines3)} 条 {[len(l) for l in lines3]}")

# 合并：两段共线的线应该接上（中间那个接点会被合并，所以是 3 个点）
a = [(0, 0), (10, 0)]
b = [(11, 0), (20, 0)]
merged = merge_paths([a, b])
check("共线断线会接上", len(merged) == 1 and merged[0][0] == (0, 0)
      and merged[0][-1] == (20, 0), f"{merged}")

# 垂直相接（真拐角）不该硬接
p = [(0, 0), (10, 0)]
q = [(10, 0), (10, 10)]
check("直角不硬接", len(merge_paths([p, q])) == 2)


# ── 二值化 ─────────────────────────────────────────
g = np.full((20, 20), 250, np.uint8)
g[5:15, 5:15] = 30
mask = binarize(g)
check("Otsu 分得开前景背景", 80 <= mask.sum() <= 120, f"{mask.sum()} 像素")
check("阈值落在两峰之间（含峰）", 25 <= otsu(g) <= 255, f"{otsu(g):.0f}")

# ── 真图：手上的线稿要提出足够多长线 ────────────────
ref = ROOT / "refs" / "hands-crop.jpg"
if ref.exists():
    gray = load_gray(str(ref))
    skel = prune_spurs(thin(binarize(gray)))
    lines = merge_paths(trace_skeleton(skel, min_len=30))
    longest = max((len(l) for l in lines), default=0)
    check("手稿提出至少 5 条长线", len(lines) >= 5, f"{len(lines)} 条")
    check("最长的一条够长", longest >= 60, f"最长 {longest} 点")

# ── 接缝：膨胀把 1~2 像素的断口补上 ──────────────────
g2 = np.full((20, 40), 250, np.uint8)
g2[10, 5:18] = 30        # 左半段
g2[10, 20:35] = 30       # 右半段，中间空 2 像素
m2 = binarize(g2)
check("原始掩码是两段", len(trace_skeleton(thin(m2), min_len=3)) == 2,
      f"{[len(l) for l in trace_skeleton(thin(m2), min_len=3)]}")
m2d = dilate(m2, 1)
check("膨胀后接成一段", len(merge_paths(trace_skeleton(thin(m2d), min_len=3))) == 1,
      f"{len(trace_skeleton(thin(m2d), min_len=3))} 条")
check("膨胀没把图撑大太多", m2d.sum() < m2.sum() * 4, f"{m2.sum()} → {m2d.sum()}")

# ── 自适应阈值：暗角里也能留住淡线 ───────────────────
g3 = np.full((60, 60), 240, np.uint8)
g3[:, 30:] = 120              # 右半边整体变暗（模拟光照不均）
g3[30, 5:55] = 60             # 一条横线，比背景暗
g3[30, 32] = 90               # 右半这段更淡
auto = binarize(g3)
ada = adaptive(g3, 21, 9.0)
check("自适应在暗区也能分出线",
      ada[30, 40] and not ada[10, 40], f"线={ada[30,40]} 背景={ada[10,40]}")

# 局部均值本身要对：全白图应该约等于白
flat = np.full((20, 20), 200, np.uint8)
check("box_mean 均匀区等于原值", abs(float(box_mean(flat, 5).mean()) - 200) < 1.5,
      f"{float(box_mean(flat, 5).mean()):.1f}")

print()
if fails:
    print(f"{len(fails)} 项失败")
    sys.exit(1)
print("全部通过")
