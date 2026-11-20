"""模糊：对一张 QImage 做可分离盒式模糊（连做三遍 ≈ 高斯）。

为什么要自己写：Qt 在离屏 `QImage` 上没有现成的模糊，`QGraphicsBlurEffect`
要拖着整个 QGraphicsScene 走，代价比这十行大多了。

三个关键点：
1. **必须预乘 alpha 再模糊**。直接模糊非预乘的 RGBA，边缘会渗出黑边
   （alpha 从 0 变 1 的地方，颜色是没定义的）。
2. 用累积和做窗口求和，代价与半径无关；半径 40 和半径 4 差不多快。
3. 大半径先降一半再模糊。模糊本来就是低频，缩一半肉眼几乎看不出，
   但快 4 倍 —— 4K 上这条决定了"能用"还是"等 8 秒"。
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage


def _box_x(a: np.ndarray, r: int) -> np.ndarray:
    """沿第 1 轴（宽）做窗口均值，两端用边缘值延拓。"""
    if r < 1:
        return a
    head = np.repeat(a[:, :1, :], r + 1, axis=1)
    tail = np.repeat(a[:, -1:, :], r, axis=1)
    padded = np.concatenate([head, a, tail], axis=1)
    c = np.cumsum(padded, axis=1, dtype=np.float32)
    return (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / np.float32(2 * r + 1)


def _blur_core(img: QImage, r: int) -> QImage:
    img = img.convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    stride = img.bytesPerLine()
    buf = np.frombuffer(img.constBits(), dtype=np.uint8)
    arr = buf.reshape(h, stride // 4, 4)[:, :w, :].astype(np.float32)

    # 预乘
    alpha = arr[:, :, 3:4] / np.float32(255.0)
    stack = np.concatenate([arr[:, :, :3] * alpha, arr[:, :, 3:4]], axis=2)
    stack = np.ascontiguousarray(stack)

    for _ in range(3):
        stack = _box_x(stack, r)
        # 转置一次做竖向；转置是拷贝，但总比逐元素快
        stack = np.ascontiguousarray(stack.transpose(1, 0, 2))
        stack = _box_x(stack, r)
        stack = np.ascontiguousarray(stack.transpose(1, 0, 2))

    a2 = stack[:, :, 3:4]
    safe_a = np.maximum(a2, np.float32(1.0))
    out_rgb = np.clip(stack[:, :, :3] * np.float32(255.0) / safe_a, 0, 255)
    out_rgb = np.where(a2 > 0.5, out_rgb, 0.0)
    out = np.concatenate([out_rgb, np.clip(a2, 0, 255)], axis=2).astype(np.uint8)

    data = np.ascontiguousarray(out).tobytes()
    return QImage(data, w, h, w * 4, QImage.Format_RGBA8888).copy()


def blur_image(img: QImage, radius: float) -> QImage:
    """返回模糊后的新图；radius < 0.5 时原样返回。"""
    r = int(round(float(radius)))
    if r < 1 or img.isNull():
        return img
    k = 2 if r >= 8 else 1
    if k == 1:
        return _blur_core(img, r)
    w, h = img.width(), img.height()
    small = img.scaled(max(1, w // k), max(1, h // k),
                       Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    small = _blur_core(small, max(1, round(r / k)))
    return small.scaled(w, h, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
