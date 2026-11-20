"""笔触纹理：程序化生成的灰度遮罩。

不下载任何素材 —— 全部用 numpy 现算，按名字缓存。
好处是：可复现（同一 seed 出同一张）、无授权问题、参数可调。

四种纹理：
- `paper`  纸纹：多倍频值噪声，温和的明暗起伏，给平涂加"纤维感"
- `grain`  颗粒：白噪声，细密的沙点
- `dry`    飞白：阈值化的噪声 —— 有真正的空洞，模拟干笔/炭笔吃不上墨
- `fiber`  纤维：方向性噪声（横向拉长），像毛边纸或者木纹

遮罩的用法：把它当 alpha 蒙版乘到笔迹层上（DestinationIn），
所以返回的都是 **灰度、alpha=亮度** 的 QImage。
"""
from __future__ import annotations

import numpy as np
from PySide6.QtGui import QImage

from .rng import seed_hash

TILE = 256
_cache: dict[tuple[str, int], QImage] = {}


def _smoothstep(x):
    return x * x * (3.0 - 2.0 * x)


def _value_noise(w: int, h: int, cells: int, rng, octaves: int = 4,
                 stretch: tuple[float, float] = (1.0, 1.0)) -> np.ndarray:
    """周期性值噪声（多倍频）。周期性 = 平铺时不留缝。"""
    total = np.zeros((h, w), np.float32)
    amp, norm = 1.0, 0.0
    sx, sy = stretch
    for o in range(octaves):
        cx = max(2, int(round(cells * sx * (1.7 ** o))))
        cy = max(2, int(round(cells * sy * (1.7 ** o))))
        grid = rng.random((cy, cx)).astype(np.float32)

        ys = np.linspace(0, cy, h, endpoint=False, dtype=np.float32)
        xs = np.linspace(0, cx, w, endpoint=False, dtype=np.float32)
        iy = np.floor(ys).astype(np.int32)
        ix = np.floor(xs).astype(np.int32)
        fy = _smoothstep(ys - iy)
        fx = _smoothstep(xs - ix)

        y0, y1 = iy % cy, (iy + 1) % cy
        x0, x1 = ix % cx, (ix + 1) % cx
        v00 = grid[np.ix_(y0, x0)]
        v10 = grid[np.ix_(y0, x1)]
        v01 = grid[np.ix_(y1, x0)]
        v11 = grid[np.ix_(y1, x1)]
        fx2 = fx[np.newaxis, :]
        fy2 = fy[:, np.newaxis]
        top = v00 * (1 - fx2) + v10 * fx2
        bot = v01 * (1 - fx2) + v11 * fx2
        total += (top * (1 - fy2) + bot * fy2) * amp
        norm += amp
        amp *= 0.5
    out = total / max(norm, 1e-6)
    return (out - out.min()) / max(out.max() - out.min(), 1e-6)


def _to_image(alpha: np.ndarray) -> QImage:
    """灰度 → RGBA（白色，alpha=灰度）。"""
    h, w = alpha.shape
    a = np.clip(alpha * 255.0, 0, 255).astype(np.uint8)
    rgba = np.empty((h, w, 4), np.uint8)
    rgba[:, :, :3] = 255
    rgba[:, :, 3] = a
    data = np.ascontiguousarray(rgba).tobytes()
    return QImage(data, w, h, w * 4, QImage.Format_RGBA8888).copy()


def get_tile(name: str, seed: int = 1) -> QImage | None:
    """拿一张（缓存过的）纹理遮罩。名字不认识返回 None。"""
    key = (name, seed)
    hit = _cache.get(key)
    if hit is not None:
        return hit

    # 用自己写的 FNV-1a，**不能用内置 hash()**：
    # Python 对字符串的 hash 每个进程都不一样（PYTHONHASHSEED 随机化），
    # 用它当种子会导致"同一 seed 每次渲染出不同的纸纹"—— 实测两个进程
    # 出来的像素分别是 215 和 207。可复现是这个工程的底线，不能踩。
    rng = np.random.default_rng(seed * 7919 + seed_hash(0, name, "tile") % 100000)
    if name == "paper":
        n = _value_noise(TILE, TILE, 6, rng, octaves=4)
        img = _to_image(0.72 + 0.28 * n)
    elif name == "grain":
        n = rng.random((TILE, TILE)).astype(np.float32)
        img = _to_image(0.62 + 0.38 * n)
    elif name == "dry":
        # 飞白的孔要细。一开始用 9 格噪声，孔比笔画还宽，看着像掉漆。
        n = _value_noise(TILE, TILE, 38, rng, octaves=3)
        mask = np.clip((n - 0.44) / 0.12, 0, 1)
        img = _to_image(_smoothstep(mask.astype(np.float32)))
    elif name == "fiber":
        n = _value_noise(TILE, TILE, 4, rng, octaves=3, stretch=(1.0, 6.0))
        img = _to_image(0.55 + 0.45 * n)
    else:
        return None

    _cache[key] = img
    return img


TEXTURES = ("paper", "grain", "dry", "fiber")
