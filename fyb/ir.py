"""中间表示：编译产物。画家（painter）只认这一层，不懂 DSL。

组在 resolve 阶段就被压平成绝对坐标，所以这里没有矩阵 —— 好处是画家可以很笨，
坏处是改一个组要重编译（对我们不是问题：一秒钟的事）。
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Prim:
    kind: str
    z: float = 0.0
    name: str | None = None
    line: int = 0
    # 填充/描边
    fill: str | None = None
    stroke: str | None = None
    width: float = 0.0
    alpha: float = 1.0
    # 几何
    points: list[tuple[float, float]] = field(default_factory=list)
    rect: tuple[float, float, float, float] | None = None
    radius: float | None = None
    closed: bool = False
    smooth: float = 1.0         # 0=折线 1=平滑
    # 笔
    pen: dict = field(default_factory=dict)
    # 文字
    text: str = ""
    size: float = 24.0
    align: str = "left"
    font: str = "Microsoft YaHei"
    tracking: float = 0.0
    hand: float = 0.0
    # 裁剪：一串名字，按顺序**求交**（嵌套 clip 就是交出来的）
    clip: tuple[str, ...] = ()
    # 混合模式：normal / multiply / screen / overlay / …
    blend: str = "normal"
    # 模糊分组：同 id 的连续图元先画到一层，模糊后再合成（0 = 不模糊）
    blur_id: int = 0
    blur_radius: float = 0.0
    blur_alpha: float = 1.0
    # 组透明：自己在哪几层"带 alpha 的组"里（外 → 内，空 = 不在任何组层里）
    groups: tuple[int, ...] = ()
    # along 被 use 复制时，多带一层变换：along 没有自己的几何，
    # 位置全靠 ref 路径算，所以"把它挪走"只能靠这个矩阵。
    mate: tuple | None = None
    # 投影（kind == "shadow" 时有效）
    ref: str | None = None
    dx: float = 0.0
    dy: float = 0.0
    blur: float = 0.0
    # 投影按轮廓外扩多少像素：>0 就是"贴着轮廓走"的阴影（不靠整体偏移）
    spread: float = 0.0
    # 真图层：同一 id 的图元先画进自己的缓冲，再整体合成一次（0 = 不在图层里）
    layer_id: int = 0
    # 渐变（kind == "grad" 时有效）
    grad: dict = field(default_factory=dict)
    # 显式写了 fill=none stroke=none：只当几何用（给 clip / hatch 当靶子），不画
    invisible: bool = False


@dataclass
class Scene:
    width: int = 1920
    height: int = 1080
    bg: str = "#f8f5ec"
    prims: list[Prim] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    meta: dict = field(default_factory=dict)
    hand: dict = field(default_factory=dict)
    groups: dict[str, list[int]] = field(default_factory=dict)
    # 组号 → 组的 alpha（只有 alpha<1 的组才在这里）
    group_alpha: dict[int, float] = field(default_factory=dict)
    # 真图层：id → (alpha, blend)。层内的重叠只算一次，不会重复混合
    layer_alpha: dict[int, float] = field(default_factory=dict)
    layer_blend: dict[int, str] = field(default_factory=dict)

    def by_name(self, name: str):
        for p in self.prims:
            if p.name == name:
                return p
        return None

    def to_dict(self) -> dict:
        import dataclasses
        return {
            "canvas": [self.width, self.height],
            "bg": self.bg,
            "meta": self.meta,
            "prims": [dataclasses.asdict(p) for p in self.prims],
        }
