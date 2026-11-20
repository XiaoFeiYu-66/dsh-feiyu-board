"""参考图 → 点列：把"用眼睛读点"换成算法。

两种模式：

- `skeleton`：线稿专用。二值化 → Zhang-Suen 细化（把线缩成 1 像素骨架）
  → 沿骨架走向拆成若干条折线。得到的是**笔画的中线**，
  所以之后能用我自己的笔重描一遍，抖动和出锋都还是我的。

- `contour`：照片专用。二值化 → Moore 邻域边界跟踪 → 得到**物体外缘**。
  给填充、走线、剪裁当靶子用。

两样最后都过一遍 Douglas-Peucker 简化：几百个像素点压到几十个，
不然生成的 .fyb 会大得没法看，也没法治。

为什么不用 vtracer：它给的是"填好色的形状"，我要的是"一条能拿笔描的路径"。
"""
from __future__ import annotations

import numpy as np
from PIL import Image


# ── 二值化 ───────────────────────────────────────────

def load_gray(path: str) -> np.ndarray:
    img = Image.open(path).convert("L")
    return np.asarray(img, dtype=np.uint8)


def otsu(gray: np.ndarray) -> float:
    hist, _ = np.histogram(gray, bins=256, range=(0, 256))
    total = hist.sum()
    if total == 0:
        return 128.0
    omega = np.cumsum(hist) / total
    mu = np.cumsum(hist * np.arange(256)) / total
    mu_t = mu[-1]
    denom = omega * (1.0 - omega)
    denom[denom == 0] = 1e-9
    sigma = (mu_t * omega - mu) ** 2 / denom
    return float(np.argmax(sigma))


def binarize(gray: np.ndarray, threshold: float | None = None,
             invert: bool = False) -> np.ndarray:
    """返回 True = 墨/物体。

    Otsu 返回的是"暗类的最大灰度值"，所以判据要用 `<=`。
    用 `<` 的话，正好落在阈值上的那些像素（两峰很尖的时候就是整片前景）
    会被整片漏掉 —— 实测一张 20×20 的双峰图会得到 0 个前景像素。
    """
    t = otsu(gray) if threshold is None else threshold * 255.0
    ink = gray <= t
    return ~ink if invert else ink


# ── Zhang-Suen 细化 ─────────────────────────────────

def thin(mask: np.ndarray, max_iter: int = 200) -> np.ndarray:
    """把粗线缩成 1 像素骨架。两遍一轮，直到不再变化。"""
    img = mask.astype(np.uint8).copy()
    for _ in range(max_iter):
        changed = False
        for step in (0, 1):
            p = np.pad(img, 1)
            p2 = p[:-2, 1:-1]
            p3 = p[:-2, 2:]
            p4 = p[1:-1, 2:]
            p5 = p[2:, 2:]
            p6 = p[2:, 1:-1]
            p7 = p[2:, :-2]
            p8 = p[1:-1, :-2]
            p9 = p[:-2, :-2]
            seq = [p2, p3, p4, p5, p6, p7, p8, p9]
            b = sum(seq)
            a = sum(((seq[i] == 0) & (seq[(i + 1) % 8] == 1)).astype(np.uint8)
                    for i in range(8))
            if step == 0:
                cond = ((p2 * p4 * p6) == 0) & ((p4 * p6 * p8) == 0)
            else:
                cond = ((p2 * p4 * p8) == 0) & ((p2 * p6 * p8) == 0)
            kill = (img == 1) & (b >= 2) & (b <= 6) & (a == 1) & cond
            if kill.any():
                img[kill] = 0
                changed = True
        if not changed:
            break
    return img.astype(bool)


# ── 骨架 → 折线 ─────────────────────────────────────

_NB = [(-1, -1), (-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1)]


def box_mean(a: np.ndarray, win: int) -> np.ndarray:
    """局部均值（积分图，O(1) 每个像素）。"""
    pad = win // 2
    ap = np.pad(a.astype(np.float32), pad, mode="edge")
    ii = np.cumsum(np.cumsum(ap, axis=0), axis=1)
    ii = np.pad(ii, ((1, 0), (1, 0)))
    h, w = a.shape
    s = (ii[win:win + h, win:win + w] - ii[0:h, win:win + w]
         - ii[win:win + h, 0:w] + ii[0:h, 0:w])
    return s / float(win * win)


def adaptive(gray: np.ndarray, win: int = 25, k: float = 9.0,
             invert: bool = False) -> np.ndarray:
    """自适应二值化：比**局部均值**暗 k 个灰阶才算墨。

    为什么需要它：手绘线稿的线深浅不均（铅笔压力、扫描光照），
    全局 Otsu 只能迁就"最黑的那几笔"，淡的线段直接掉成背景 ——
    描出来就是断的。自适应每块区域用自己的基准，淡线也能留下。
    """
    m = box_mean(gray, max(3, win | 1))
    ink = gray.astype(np.float32) < (m - k)
    return ~ink if invert else ink


def dilate(mask: np.ndarray, r: int = 1) -> np.ndarray:
    """膨胀 r 圈（8 邻域）。

    为什么要这一步：铅笔线深浅不均，浅的那几个像素二值化时掉成背景，
    骨架就在这里断开 —— 描出来是一串虚线。
    先膨胀 1~2 像素把缝接上，细化时反正会把粗细变回 1 像素，不影响形状。
    """
    out = mask.astype(bool).copy()
    for _ in range(max(0, r)):
        p = np.pad(out, 1, mode="constant", constant_values=False)
        acc = np.zeros_like(out)
        for dy in (0, 1, 2):
            for dx in (0, 1, 2):
                acc |= p[dy:dy + out.shape[0], dx:dx + out.shape[1]]
        out = acc
    return out


def _deg(img: np.ndarray, p) -> int:
    y, x = p
    h, w = img.shape
    return sum(1 for dy, dx in _NB
               if 0 <= y + dy < h and 0 <= x + dx < w and img[y + dy, x + dx])


def prune_spurs(skel: np.ndarray, max_len: int = 9, rounds: int = 10) -> np.ndarray:
    """剪掉毛刺。

    铅笔线的骨架不是干净的一根：笔触边缘的凹凸会在骨架上留下小侧枝，
    每个侧枝都是一个三岔点 —— 我的走线一遇到三岔点就停，于是整条轮廓
    被切成几十段（实测 41 段、最长只有 65 像素）。先把侧枝剪掉。
    """
    img = skel.astype(np.uint8).copy()
    for _ in range(rounds):
        ends = [(y, x) for y, x in zip(*np.nonzero(img)) if _deg(img, (y, x)) == 1]
        removed = False
        for start in ends:
            if img[start] == 0:
                continue
            path = [start]
            cur, prev = start, None
            for _ in range(max_len):
                nbs = [n for n in _NB
                       if 0 <= cur[0] + n[0] < img.shape[0]
                       and 0 <= cur[1] + n[1] < img.shape[1]
                       and img[cur[0] + n[0], cur[1] + n[1]] == 1
                       and (cur[0] + n[0], cur[1] + n[1]) != prev]
                if len(nbs) != 1:
                    break
                prev, cur = cur, (cur[0] + nbs[0][0], cur[1] + nbs[0][1])
                path.append(cur)
                if _deg(img, cur) >= 3:
                    break
            if _deg(img, cur) >= 3 and len(path) <= max_len:
                for yy, xx in path[:-1]:
                    img[yy, xx] = 0
                removed = True
        if not removed:
            break
    return img.astype(bool)


def merge_paths(lines: list[list[tuple[int, int]]], tol: float = 3.0,
                max_gap_dir: float = 0.8) -> list[list[tuple[int, int]]]:
    """把断成两截的线接回去：端点靠得近、方向也一致就合并。"""
    def d(a, b):
        return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5

    def dir_of(line, at_end):
        if len(line) < 2:
            return None
        a, b = (line[-2], line[-1]) if at_end else (line[1], line[0])
        v = (b[0] - a[0], b[1] - a[1])
        n = (v[0] ** 2 + v[1] ** 2) ** 0.5 or 1.0
        return (v[0] / n, v[1] / n)

    lines = [list(l) for l in lines if l]
    changed = True
    while changed:
        changed = False
        for i in range(len(lines)):
            if not lines[i]:
                continue
            for j in range(len(lines)):
                if i == j or not lines[i] or not lines[j]:
                    continue
                joined = False
                for ei in (True, False):
                    for ej in (True, False):
                        p = lines[i][-1] if ei else lines[i][0]
                        q = lines[j][0] if ej else lines[j][-1]
                        if d(p, q) > tol:
                            continue
                        di, dj = dir_of(lines[i], ei), dir_of(lines[j], ej)
                        if di and dj and (di[0] * dj[0] + di[1] * dj[1]) < max_gap_dir:
                            continue          # 方向差太多，是拐角不是断线
                        a = list(lines[i]) if ei else list(reversed(lines[i]))
                        # ej=True 说明接的是 b 的头 → b 按原顺序接在后面；
                        # 反过来（接 b 的尾）才要倒。之前这个条件写反了，
                        # 结果接上去的是 b 的尾巴，线在接点处掉头。
                        b = list(lines[j]) if ej else list(reversed(lines[j]))
                        lines[i] = a + b[1:]
                        lines[j] = []
                        joined = changed = True
                        break
                    if joined:
                        break
        lines = [l for l in lines if l]
    return lines


def trace_skeleton(skel: np.ndarray, min_len: int = 12) -> list[list[tuple[int, int]]]:
    """把骨架走成若干条折线。

    **不用"按三岔点切段"**：8 连通的骨架在普通拐角处就会有 3 个邻居，
    那会被当成分叉，一条轮廓被切成几十段（实测 41 段、最长 65 像素）。
    改成贪心走线：一路往前，岔路口挑"最顺着当前方向"的那个，
    走过的像素不再走；回头再收拾剩下的环。
    """
    ys, xs = np.nonzero(skel)
    pts = set(zip(ys.tolist(), xs.tolist()))
    if not pts:
        return []

    def deg(p):
        return sum(1 for dy, dx in _NB if (p[0] + dy, p[1] + dx) in pts)

    visited: set[tuple[int, int]] = set()
    paths: list[list[tuple[int, int]]] = []

    def walk(start):
        path = [start]
        visited.add(start)
        cur, prev_dir = start, None
        while True:
            best, best_score = None, -2.0
            for dy, dx in _NB:
                q = (cur[0] + dy, cur[1] + dx)
                if q not in pts or q in visited:
                    continue
                score = 0.0 if prev_dir is None else dy * prev_dir[0] + dx * prev_dir[1]
                if score > best_score:
                    best, best_score = q, score
            if best is None:
                break
            prev_dir = (best[0] - cur[0], best[1] - cur[1])
            path.append(best)
            visited.add(best)
            cur = best
        return path

    starts = [p for p in pts if deg(p) == 1] or list(pts)
    for s in starts:
        if s in visited:
            continue
        p = walk(s)
        if len(p) >= min_len:
            paths.append(p)
    for s in list(pts):              # 剩下的环
        if s in visited:
            continue
        p = walk(s)
        if len(p) >= min_len:
            paths.append(p)

    return [[(x, y) for y, x in p] for p in paths]


# ── 轮廓跟踪 ────────────────────────────────────────

def trace_contour(mask: np.ndarray) -> list[tuple[int, int]]:
    """沿像素"格边"走一圈，返回外轮廓（顺时针，前景恒在右手边）。

    之前用的是 Moore 邻域跟踪，结果返回空 —— 那套规则对"从哪个方向起算"
    很敏感，起始方向的索引差一格就整条走不出来。
    格边行走没有这个歧义：每一步只看"右手那个像素是不是前景"，
    是就直走、不是就右转、左边有前景就左转。
    """
    h, w = mask.shape
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return []
    sy = int(ys.min())
    sx = int(xs[ys == ys.min()].min())

    def fg(y: int, x: int) -> bool:
        return 0 <= y < h and 0 <= x < w and bool(mask[y, x])

    # 方向：0=E 1=S 2=W 3=N（右转 = +1）
    d = 0
    x, y = sx, sy
    pts = [(x, y)]
    start = (x, y, d)
    first = True
    limit = 4 * h * w
    for _ in range(limit):
        if d == 0:                                  # 向东：右手是下方
            if not fg(y, x):
                d = 1
            elif fg(y - 1, x):
                d = 3
        elif d == 1:                                # 向南：右手是西边
            if not fg(y, x - 1):
                d = 2
            elif fg(y, x):
                d = 0
        elif d == 2:                                # 向西：右手是上方
            if not fg(y - 1, x - 1):
                d = 3
            elif fg(y, x - 1):
                d = 1
        else:                                       # 向北：右手是东边
            if not fg(y - 1, x):
                d = 0
            elif fg(y - 1, x - 1):
                d = 2
        # 绕回起点（同位置同方向）就收工。注意要在"移动之前"判断，
        # 否则在拐角处会永远错过这个状态、一路绕到上限。
        if not first and (x, y, d) == start:
            break
        first = False
        if d == 0:
            x += 1
        elif d == 1:
            y += 1
        elif d == 2:
            x -= 1
        else:
            y -= 1
        pts.append((x, y))
    return pts


# ── Douglas-Peucker ─────────────────────────────────

def simplify(points: list[tuple[float, float]], eps: float = 1.5,
             closed: bool = False) -> list[tuple[float, float]]:
    if len(points) < 3:
        return points
    pts = list(points)
    if closed:
        far = max(range(len(pts)), key=lambda i: (pts[i][0] - pts[0][0]) ** 2
                  + (pts[i][1] - pts[0][1]) ** 2)
        ring = pts + [pts[0]]
        a = _dp(ring[:far + 1], eps)
        b = _dp(ring[far:], eps)
        return a[:-1] + b[:-1]
    return _dp(pts + [], eps)


def _dp(pts: list[tuple[float, float]], eps: float) -> list[tuple[float, float]]:
    if len(pts) < 3:
        return pts
    x0, y0 = pts[0]
    x1, y1 = pts[-1]
    dx, dy = x1 - x0, y1 - y0
    norm = (dx * dx + dy * dy) ** 0.5
    best, best_i = -1.0, 0
    for i in range(1, len(pts) - 1):
        px, py = pts[i]
        if norm < 1e-9:
            d = ((px - x0) ** 2 + (py - y0) ** 2) ** 0.5
        else:
            d = abs(dy * px - dx * py + x1 * y0 - y1 * x0) / norm
        if d > best:
            best, best_i = d, i
    if best <= eps:
        return [pts[0], pts[-1]]
    left = _dp(pts[:best_i + 1], eps)
    right = _dp(pts[best_i:], eps)
    return left[:-1] + right
