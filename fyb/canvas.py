"""最小画布：一张 QImage + QPainter，负责超采样和导出。

M0 只做「笔画 + 填充」，够验证笔；M1 才接图元/组/裁剪。
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QFont, QGuiApplication, QImage, QPainter, QPainterPath

from .pen import Stroke, build_stroke, stroke_path, to_qcolor
from .rng import Rng


def ensure_app():
    return QGuiApplication.instance() or QGuiApplication([])


_FONTS_READY = False


def ensure_fonts():
    """Qt 不带字体，offscreen 下也没人帮它找系统字体 —— 手动挂中文字体。"""
    global _FONTS_READY
    if _FONTS_READY:
        return
    from PySide6.QtGui import QFontDatabase
    for path in (r"C:\Windows\Fonts\msyh.ttc",
                 r"C:\Windows\Fonts\msyhl.ttc",
                 r"C:\Windows\Fonts\simhei.ttf"):
        if os.path.exists(path):
            QFontDatabase.addApplicationFont(path)
    _FONTS_READY = True


class Canvas:
    def __init__(self, width: int, height: int, bg: str = "#f8f5ec", scale: int = 2):
        ensure_app()
        self.width = int(width)
        self.height = int(height)
        self.scale = max(1, int(scale))
        self.img = QImage(self.width * self.scale, self.height * self.scale,
                          QImage.Format_ARGB32_Premultiplied)
        self.img.fill(to_qcolor(bg))
        self.painter = QPainter(self.img)
        self.painter.setRenderHint(QPainter.Antialiasing, True)
        self.painter.scale(self.scale, self.scale)
        self.ops = 0

    # -- 基本 -------------------------------------------------------------
    def stroke(self, s: Stroke, rng: Rng | None = None):
        rng = rng or Rng(0)
        pts, widths = build_stroke(s, rng)
        if len(pts) < 2:
            return None
        path = stroke_path(pts, widths, closed=s.closed, cap=s.cap)
        self.painter.setPen(Qt.NoPen)
        self.painter.setBrush(to_qcolor(s.color, s.alpha))
        self.painter.drawPath(path)
        self.ops += 1
        return pts, widths

    def fill(self, path: QPainterPath, color: str, alpha: float = 1.0):
        self.painter.setPen(Qt.NoPen)
        self.painter.setBrush(to_qcolor(color, alpha))
        self.painter.drawPath(path)
        self.ops += 1

    def text(self, x: float, y: float, body: str, size: int = 22,
             color: str = "#6b7280"):
        ensure_fonts()
        font = QFont("Microsoft YaHei")
        font.setPixelSize(int(size))
        self.painter.setFont(font)
        self.painter.setPen(to_qcolor(color))
        self.painter.drawText(QPointF(x, y), body)
        self.ops += 1

    def draw_image(self, img: QImage, x: float, y: float,
                   w: float | None = None, h: float | None = None):
        """把另一张图贴进来（sweep 拼版用）。"""
        target = img
        if w and h and (abs(w - img.width()) > 0.5 or abs(h - img.height()) > 0.5):
            target = img.scaled(int(w), int(h), Qt.IgnoreAspectRatio,
                                Qt.SmoothTransformation)
        self.painter.drawImage(QPointF(x, y), target)
        self.ops += 1

    # -- 导出 -------------------------------------------------------------
    def finish(self):
        if self.painter.isActive():
            self.painter.end()

    def save(self, path: str, downscale: bool = True):
        self.finish()
        scaled = self.img
        if downscale and self.scale != 1:
            scaled = self.img.scaled(self.width, self.height,
                                     Qt.IgnoreAspectRatio,
                                     Qt.SmoothTransformation)
        os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
        if not scaled.save(path):
            raise OSError(f"写不出去：{path}")
        return path
