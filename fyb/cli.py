"""命令行：fyb check / render / meta。"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from .compiler import compile_file
from .errors import format_all
from . import __version__

EXIT_OK, EXIT_DSL, EXIT_RENDER = 0, 2, 3


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def cmd_check(path: Path, as_json: bool) -> int:
    text = _read(path)
    t0 = time.perf_counter()
    res = compile_file(str(path))
    dt = (time.perf_counter() - t0) * 1000
    if as_json:
        print(json.dumps({
            "ok": res.ok,
            "file": str(path),
            "ms": round(dt, 1),
            "errors": [{"code": e.code, "line": e.line, "col": e.col,
                        "message": e.message} for e in res.errors],
            "prims": len(res.scene.prims) if res.scene else 0,
        }, ensure_ascii=False, indent=1))
        return EXIT_OK if res.ok else EXIT_DSL
    if not res.ok:
        print(format_all(res.errors, text, str(path)))
        return EXIT_DSL
    s = res.scene
    print(f"OK  {path}")
    print(f"  canvas {s.width}×{s.height}   bg {s.bg}   图元 {len(s.prims)}   "
          f"命令 {len(res.commands)}   编译 {dt:.1f} ms")
    for w in s.warnings:
        print(f"  警告 {w}")
    return EXIT_OK


def cmd_render(path: Path, out: Path, scale: int, fast: bool,
               dump_ir: Path | None, raw: bool = False,
               under: Path | None = None, under_alpha: float = 0.35) -> int:
    text = _read(path)
    res = compile_file(str(path))
    if not res.ok:
        print(format_all(res.errors, text, str(path)))
        return EXIT_DSL
    from .painter import render
    t0 = time.perf_counter()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        cv = render(res.scene, scale=scale, fast=fast,
                    under=under, under_alpha=under_alpha)
        cv.save(str(out), downscale=not (fast or raw))
    except Exception as ex:                       # noqa: BLE001
        print(f"渲染失败：{ex}", file=sys.stderr)
        return EXIT_RENDER
    dt = (time.perf_counter() - t0) * 1000
    if dump_ir:
        dump_ir.write_text(json.dumps(res.scene.to_dict(), ensure_ascii=False,
                                      indent=1), encoding="utf-8")
    s = res.scene
    # 报**落盘尺寸**，不是倍率。以前打 "@2x" 会让人以为文件是两倍大。
    # 三种情形不一样：--fast 根本不超采样；--raw 保留超采样；默认缩回画布尺寸。
    if fast:
        out_w, out_h = s.width, s.height
        note = "（--fast：不超采样，抗锯齿也关）"
    elif raw:
        out_w, out_h = s.width * scale, s.height * scale
        note = f"（--raw：保留 {scale}x 超采样）"
    else:
        out_w, out_h = s.width, s.height
        note = f"（{scale}x 超采样 → 缩回画布尺寸）" if scale > 1 else ""
    print(f"{out}  {out_w}×{out_h}{note}  图元 {len(s.prims)}  {dt:.0f} ms")
    return EXIT_OK


def cmd_watch(target: Path, out: Path, scale: int, settle: float,
              status: Path) -> int:
    """盯着场景目录：文件一变就重画一张预览图。

    预览图固定写到 `renders/_preview.png`（gallery 会跳过下划线开头的文件），
    状态写进 `.state/preview.json`，插件面板靠它显示"预览 · 场景名 · 几秒前"。

    用轮询 mtime 而不是 watchdog：少一个依赖，Windows 上也够准。
    """
    import socket

    from .painter import render

    # 单实例：抢一个本地端口当锁。插件重启、我手动起、两边都想跑的时候，
    # 后来者立刻退出 —— 否则会有两个进程同时写 _preview.png。
    lock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    # Windows 默认允许两个 socket 绑同一个端口（不像 Linux），
    # 要显式排他，否则这道锁形同虚设。
    if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
        lock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    try:
        lock.bind(("127.0.0.1", 18991))
        lock.listen(1)
    except OSError:
        print("已经有一个 fyb watch 在跑了，这个退出。", flush=True)
        return EXIT_OK

    def stamp(p: Path) -> float:
        try:
            return p.stat().st_mtime
        except OSError:
            return 0.0

    def scan() -> dict[Path, float]:
        if target.is_file():
            return {target: stamp(target)}
        out_map = {}
        for p in sorted(target.glob("*.fyb")):
            out_map[p] = stamp(p)
        return out_map

    def write_status(payload: dict) -> None:
        try:
            status.parent.mkdir(parents=True, exist_ok=True)
            status.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass

    def shoot(path: Path) -> None:
        t0 = time.perf_counter()
        res = compile_file(str(path))
        if not res.ok:
            first = res.errors[0] if res.errors else None
            msg = (f"{first.code} 第 {first.line} 行：{first.message}" if first
                   else "编译失败")
            print(f"[{time.strftime('%H:%M:%S')}] {path.name}  ✗ {msg}", flush=True)
            write_status({"ok": False, "scene": path.stem, "error": msg,
                          "at": int(time.time() * 1000)})
            return
        try:
            cv = render(res.scene, scale=scale)
            cv.save(str(out), downscale=False)
        except Exception as ex:                    # noqa: BLE001
            print(f"[{time.strftime('%H:%M:%S')}] {path.name}  ✗ 渲染失败：{ex}",
                  flush=True)
            write_status({"ok": False, "scene": path.stem, "error": f"渲染失败：{ex}",
                          "at": int(time.time() * 1000)})
            return
        dt = (time.perf_counter() - t0) * 1000
        print(f"[{time.strftime('%H:%M:%S')}] {path.name}  → {out.name}  "
              f"{len(res.scene.prims)} 图元  {dt:.0f} ms", flush=True)
        write_status({"ok": True, "scene": path.stem, "png": out.name,
                      "prims": len(res.scene.prims), "ms": round(dt),
                      "at": int(time.time() * 1000)})

    seen = scan()
    print(f"盯着 {target}{'（单个文件）' if target.is_file() else '（目录）'}，"
          f"改动就重画到 {out.name}；Ctrl+C 退出", flush=True)
    # 先画一张，省得打开面板时是空白
    newest = max(seen, key=lambda p: seen[p], default=None)
    if newest and seen[newest] > 0:
        shoot(newest)

    try:
        while True:
            time.sleep(max(0.1, settle / 2))
            now = scan()
            changed = [p for p, t in now.items() if seen.get(p) != t]
            if not changed:
                continue
            # 等一下让它稳定（编辑器保存往往触发两次事件）
            time.sleep(settle)
            now = scan()
            for p in changed:
                seen[p] = now.get(p, 0.0)
                if p.exists():
                    shoot(p)
            for p in list(seen):
                if p not in now:
                    seen.pop(p)
    except KeyboardInterrupt:
        print("停了", flush=True)
        return EXIT_OK


def cmd_trace(img: Path, out: Path, mode: str, threshold: float | None,
              min_len: int, eps: float, height: int, max_lines: int,
              ink: str, width: float, invert: bool, dilate_by: int,
              join: float, adaptive_win: int, adaptive_k: float) -> int:
    """参考图 → 场景骨架。算法读点，不靠眼睛。"""
    from .trace import (adaptive, binarize, dilate, load_gray, merge_paths,
                        prune_spurs, simplify, thin, trace_contour,
                        trace_skeleton)

    gray = load_gray(str(img))
    ih, iw = gray.shape
    # 骨架模式默认阈值 0.86，不用 Otsu：
    # Otsu 只迁就"最黑的那几笔"，铅笔稿淡的地方会掉成背景，描出来就是断线
    # （实测 Otsu≈0.68 时，一只手被切成 27 个连通块）。
    if threshold is None and mode == "skeleton":
        threshold = 0.86
    if adaptive_win and mode == "skeleton":
        mask = adaptive(gray, adaptive_win, adaptive_k, invert=invert)
    else:
        mask = binarize(gray, threshold, invert=invert)
    if not mask.any():
        print("这张图里没找到墨迹/物体（试试 --invert 或 --threshold）", file=sys.stderr)
        return EXIT_DSL

    if mode == "skeleton":
        # 先接缝再细化：淡的地方二值化会断，膨胀 1~2 像素补回来
        mask = dilate(mask, dilate_by)
        skel = prune_spurs(thin(mask))
        raw = trace_skeleton(skel, min_len=min_len)
        covered = sum(len(p) for p in raw)
        total = int(skel.sum())
        raw = merge_paths(raw, tol=join)
        closed = False
    else:
        c = trace_contour(mask)
        raw = [c] if c else []
        closed = True
    if not raw:
        print("没提出任何线（试试调小 --min-len 或换模式）", file=sys.stderr)
        return EXIT_DSL

    # 长线优先：手绘线稿会有很多碎屑，先留主要的
    raw.sort(key=len, reverse=True)
    raw = raw[:max_lines]

    cw = int(round(height * iw / ih))
    k = height / ih
    lines = []
    for pts in raw:
        p = [(x * k, y * k) for x, y in pts]
        p = simplify(p, eps, closed=closed)
        if len(p) >= (3 if closed else 2):
            lines.append(p)

    def fmt(pts):
        return " ".join(f"{x:.0f},{y:.0f}" for x, y in pts)

    body = []
    for p in lines:
        body.append(f"curve [{fmt(p)}] w={width:g} stroke={ink}"
                    + (" closed" if closed else "")
                    + " tex=paper tex_scale=0.4 jitter=0.5 taper=0")

    text = f"""canvas {cw}x{height}
bg #F2ECDF

# 由 `fyb trace` 从 {img.name} 提出（{mode} 模式）；点是算法给的，不是眼睛读的。
# 对照渲染：fyb render {out.name} --under {img.as_posix()}
hand preset=pencil seed=77

{chr(10).join(body)}
"""
    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        out.write_text(text, encoding="utf-8")
    except OSError as ex:
        print(f"写不了 {out}：{ex}", file=sys.stderr)
        return EXIT_RENDER
    n = sum(len(p) for p in lines)
    cov = ""
    if mode == "skeleton" and total:
        cov = f"，骨架覆盖 {covered / total:.0%}"
    print(f"{out}  {cw}×{height}  {len(lines)} 条线 / {n} 个点"
          f"（原图 {iw}×{ih}，简化 eps={eps:g}{cov}）")
    return EXIT_OK


def cmd_balance(path: Path, out: Path | None, cols: int, rows: int,
                grid_kind: str, no_png: bool) -> int:
    """构图体检：覆盖率网格 + 重心 + 空角，并写一张标注图。"""
    from .balance import analyze, annotate, format_grid
    from .painter import render

    res = compile_file(str(path))
    if not res.ok:
        print(format_all(res.errors, _read(path), str(path)))
        return EXIT_DSL
    cv = render(res.scene, scale=1)
    # 拿场景自己的底色当"空"的基准 —— 否则米色/深色底的画面会被量成 100% 满
    bg = (255, 255, 255)
    raw = (res.scene.bg or "#ffffff").lstrip("#")
    if len(raw) == 6:
        bg = (int(raw[0:2], 16), int(raw[2:4], 16), int(raw[4:6], 16))
    b = analyze(cv.img, cols=cols, rows=rows, bg=bg)

    print(f"{path.name}  {cv.img.width()}×{cv.img.height()}  "
          f"覆盖率 {b.coverage:.1%}  重心 ({b.centroid[0]:.2f}, {b.centroid[1]:.2f})")
    print(format_grid(b))
    if b.notes:
        print("提示：")
        for n in b.notes:
            print("  · " + n)

    if not no_png:
        target = out or (Path("renders") / f"_balance_{path.stem}.png")
        target.parent.mkdir(parents=True, exist_ok=True)
        annotate(cv.img, b, grid_kind=grid_kind).save(str(target))
        print(f"体检图：{target}")
    return EXIT_OK


def cmd_posterize(img: Path, out: Path, colors: int, blur: float, eps: float,
                  height: int, min_area: int, win: int) -> int:
    """图 → 按颜色分层的场景。适合色块分明的插画/图标。"""
    from .posterize import vectorize

    try:
        text, stats = vectorize(img, colors=colors, blur=blur, eps=eps,
                                height=height, min_area=min_area, win=win,
                                title=out.stem)
    except FileNotFoundError:
        print(f"文件不存在：{img}", file=sys.stderr)
        return EXIT_DSL
    except Exception as ex:                     # noqa: BLE001
        print(f"矢量化失败：{ex}", file=sys.stderr)
        return EXIT_RENDER

    out.parent.mkdir(parents=True, exist_ok=True)
    try:
        out.write_text(text, encoding="utf-8")
    except OSError as ex:
        print(f"写不了 {out}：{ex}", file=sys.stderr)
        return EXIT_RENDER
    print(f"{out}  {stats['width']}×{stats['height']}  "
          f"{stats['regions']} 个色块 / {stats['points']} 个点"
          f"（{colors} 色，模糊 {blur:g}，容差 {eps:g}）")
    return EXIT_OK


def cmd_meta(path: Path) -> int:
    res = compile_file(str(path))
    if not res.ok:
        print(format_all(res.errors, _read(path), str(path)))
        return EXIT_DSL
    s = res.scene
    kinds: dict[str, int] = {}
    for p in s.prims:
        kinds[p.kind] = kinds.get(p.kind, 0) + 1
    print(json.dumps({
        "canvas": [s.width, s.height],
        "bg": s.bg,
        "prims": kinds,
        "total": len(s.prims),
        "names": [p.name for p in s.prims if p.name],
        "inks": [p.pen for p in s.prims if p.kind == "ink"][:2],
    }, ensure_ascii=False, indent=1))
    return EXIT_OK


FEEDBACK = {
    "too_messy":    {"jitter": -0.12},
    "too_tidy":     {"jitter": +0.12},
    "too_straight": {"wavelength": +12.0},
    "too_wiggly":   {"wavelength": -12.0},
    "too_thin":     {"width": "x1.15"},
    "too_thick":    {"width": "x0.87"},
    "too_stiff":    {"taper": +0.10},
    "too_soft":     {"taper": -0.10},
}

CLAMP = {"jitter": (0.0, 3.0), "taper": (0.0, 1.0), "wavelength": (8.0, 400.0),
         "width": (0.5, 60.0), "roughness": (0.4, 2.5)}


def _apply_feedback(hand: dict, tags: list[str]) -> list[str]:
    changes = []
    for tag in tags:
        rule = FEEDBACK.get(tag)
        if not rule:
            changes.append(f"  ? 不认识 {tag!r}（可用：{', '.join(FEEDBACK)}）")
            continue
        for key, val in rule.items():
            before = hand.get(key)
            if before is None:
                before = 3.0 if key == "width" else 0.0
            if isinstance(val, str) and val.startswith("x"):
                after = float(before) * float(val[1:])
            else:
                after = float(before) + float(val)
            lo, hi = CLAMP.get(key, (None, None))
            if lo is not None:
                after = max(lo, min(hi, after))
            hand[key] = after
            changes.append(f"  {key}: {float(before):.3f} → {after:.3f}   ({tag})")
    return changes


def _hand_line(hand: dict) -> str:
    parts = ["hand"]
    if hand.get("preset"):
        parts.append(f"preset={hand['preset']}")
    for key in ("jitter", "taper", "wavelength", "width", "roughness", "seed"):
        if hand.get(key) is not None:
            parts.append(f"{key}={round(float(hand[key]), 4):g}")
    return " ".join(parts)


def cmd_feedback(path: Path, tags: list[str], apply: bool) -> int:
    src = _read(path)
    res = compile_file(str(path))
    if not res.ok:
        print(format_all(res.errors, src, str(path)))
        return EXIT_DSL
    hand = dict(res.scene.hand)
    print(f"当前手感：{_hand_line(hand)}")
    changes = _apply_feedback(hand, tags)
    for c in changes:
        print(c)
    new_line = _hand_line(hand)
    print(f"建议改成：{new_line}")
    if not apply:
        print("\n（加 --apply 就写回场景文件）")
        return EXIT_OK

    lines = src.splitlines()
    idx = next((i for i, ln in enumerate(lines) if ln.strip().startswith("hand ")), None)
    if idx is not None:
        # 只留第一行 hand：后面那些本来就会覆盖它，留着只会让人以为改没生效
        lines = [ln for i, ln in enumerate(lines)
                 if i == idx or not ln.strip().startswith("hand ")]
        idx = next(i for i, ln in enumerate(lines) if ln.strip().startswith("hand "))
        lines[idx] = new_line
        out = lines
    else:
        out, done = [], False
        for ln in lines:
            out.append(ln)
            if not done and ln.strip().lower().startswith(("canvas", "bg")):
                out.append(new_line)
                done = True
        if not done:
            out.insert(1, new_line)
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"已写回 {path}")
    return EXIT_OK


def _with_preset(src: str, preset: str) -> str:
    """把源文件里现有的 hand 行摘掉，在 canvas 行后面插一行新的预设。"""
    out, done = [], False
    for ln in src.splitlines():
        if ln.strip().startswith("hand "):
            continue
        out.append(ln)
        if not done and ln.strip().lower().startswith("canvas"):
            out.append(f"hand preset={preset}")
            done = True
    return "\n".join(out) + "\n"


def cmd_sweep(path: Path, out: Path, sets: list[str], cols: int, cell: int) -> int:
    """一次出 N 格不同参数的对比图 —— 这是给"一次只能看一张"配的放大器。"""
    import copy
    import itertools

    res = compile_file(str(path))
    if not res.ok:
        print(format_all(res.errors, _read(path), str(path)))
        return EXIT_DSL

    axes = []
    for s in sets:
        key, _, vals = s.partition("=")
        if not vals:
            print(f"--set 要写成 key=v1,v2，收到 {s!r}", file=sys.stderr)
            return EXIT_DSL
        axes.append((key.strip().lower(), [v.strip() for v in vals.split(",")]))

    combos = list(itertools.product(*[v for _, v in axes]))
    limit = 24
    if len(combos) > limit:
        print(f"格子太多（{len(combos)}），只画前 {limit} 个", file=sys.stderr)
        combos = combos[:limit]

    from .canvas import Canvas
    from .painter import render

    PEN_KEYS = {"jitter", "taper", "rough", "roughness", "wave", "wavelength",
                "width", "step"}
    cells = []
    src = _read(path)
    for combo in combos:
        preset = next((v for (k, _), v in zip(axes, combo) if k == "preset"), None)
        if preset:
            from .compiler import compile_text
            r2 = compile_text(_with_preset(src, preset))
            if not r2.ok:
                print(f"preset={preset} 编不过：{r2.errors[0].message}", file=sys.stderr)
                continue
            scene = r2.scene
        else:
            scene = copy.deepcopy(res.scene)
        label = []
        for (key, _), val in zip(axes, combo):
            label.append(f"{key}={val}")
            if key == "preset":
                continue
            target = "roughness" if key == "rough" else key
            if target == "seed":
                scene.hand["seed"] = float(val)
            elif target in PEN_KEYS:
                scene.hand[target] = float(val)
                for p in scene.prims:
                    if p.kind == "ink":
                        p.pen[target] = float(val)
        cv = render(scene, scale=1, fast=False)
        cells.append((" ".join(label), cv.img))

    cols = max(1, min(cols, len(cells)))
    rows = (len(cells) + cols - 1) // cols
    sw, sh = res.scene.width, res.scene.height
    ch = int(round(cell * sh / sw))
    pad, label_h = 10, 28
    sheet = Canvas(cols * (cell + pad) + pad, rows * (ch + label_h + pad) + pad,
                   bg="#f4efe2", scale=1)
    for i, (label, img) in enumerate(cells):
        r_, c_ = divmod(i, cols)
        x = pad + c_ * (cell + pad)
        y = pad + r_ * (ch + label_h + pad)
        sheet.draw_image(img, x, y, cell, ch)
        sheet.text(x + 4, y + ch + 19, label, 18, "#5b5347")
    sheet.save(str(out), downscale=True)
    print(f"{out}  {cols}×{rows} 格  {len(cells)} 个变体")
    return EXIT_OK


def cmd_anim(path: Path, out: Path, frames: int, duration: int,
             scale: int) -> int:
    """逐笔动画：第 i 帧只画前 i 个图元，拼成 APNG。"""
    import io

    res = compile_file(str(path))
    if not res.ok:
        print(format_all(res.errors, _read(path), str(path)))
        return EXIT_DSL

    from PySide6.QtCore import QBuffer, QByteArray, QIODevice
    from PIL import Image
    from .painter import render

    total = len([p for p in res.scene.prims if not p.invisible])
    n = max(1, min(frames or total, total))
    if n >= total:
        steps = list(range(1, total + 1))
    else:
        steps = sorted({max(1, round(total * k / n)) for k in range(1, n + 1)})

    imgs = []
    for k in steps:
        cv = render(res.scene, scale=scale, max_ops=k)
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(QIODevice.WriteOnly)
        cv.img.save(buf, "PNG")
        buf.close()
        imgs.append(Image.open(io.BytesIO(bytes(ba))).convert("RGBA"))

    delays = [duration] * len(imgs)
    delays[-1] = duration * 8          # 最后一帧停久一点
    imgs[0].save(str(out), save_all=True, append_images=imgs[1:],
                 duration=delays, loop=0, format="PNG", disposal=1)
    print(f"{out}  {len(imgs)} 帧  {scale}×  {out.stat().st_size / 1024:.0f} KB")
    return EXIT_OK


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:                             # noqa: BLE001
        pass
    ap = argparse.ArgumentParser(prog="fyb", description="小飞鱼画板")
    ap.add_argument("--version", action="version", version=f"fyb {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("check", help="只编译，不出图")
    c.add_argument("file")
    c.add_argument("--json", action="store_true")

    r = sub.add_parser("render", help="编译并出图")
    r.add_argument("file")
    r.add_argument("--out", default=None)
    r.add_argument("--scale", type=int, default=2)
    r.add_argument("--fast", action="store_true", help="1×、关抗锯齿")
    r.add_argument("--raw", action="store_true", help="保存超采样原图（不缩回逻辑尺寸）")
    r.add_argument("--under", default=None, help="垫底稿：参考图垫在最下面（临摹用）")
    r.add_argument("--under-alpha", type=float, default=0.35, help="垫底不透明度")
    r.add_argument("--ir", default=None, help="顺便导出一份 IR（json）")

    m = sub.add_parser("meta", help="看看图元统计")
    m.add_argument("file")

    s = sub.add_parser("sweep", help="一次出 N 格不同参数的对比图")
    s.add_argument("file")
    s.add_argument("--set", dest="sets", action="append", required=True,
                   metavar="key=v1,v2")
    s.add_argument("--cols", type=int, default=2)
    s.add_argument("--cell", type=int, default=760, help="每格宽度（像素）")
    s.add_argument("--out", default=None)

    fb = sub.add_parser("feedback", help="按反馈挪手感参数")
    fb.add_argument("file")
    fb.add_argument("--tags", required=True,
                    help="逗号分隔，如 too_messy,too_thin")
    fb.add_argument("--apply", action="store_true", help="写回场景文件")

    an = sub.add_parser("anim", help="逐笔动画（APNG）")
    an.add_argument("file")
    an.add_argument("--out", default=None)
    an.add_argument("--frames", type=int, default=0, help="0 = 每个图元一帧")
    an.add_argument("--duration", type=int, default=110, help="每帧毫秒")
    an.add_argument("--scale", type=int, default=1)

    w = sub.add_parser("watch", help="盯着场景，改了自动重画预览图")
    w.add_argument("target", help="一个 .fyb，或一个目录")
    w.add_argument("--out", default=None, help="预览图路径（默认 renders/_preview.png）")
    w.add_argument("--scale", type=int, default=1)
    w.add_argument("--settle", type=float, default=0.35, help="改动后等多久再画（秒）")
    w.add_argument("--status", default=None, help="状态文件（默认 .state/preview.json）")

    tr = sub.add_parser("trace", help="参考图 → 场景骨架（算法读点）")
    tr.add_argument("image")
    tr.add_argument("--out", default=None)
    tr.add_argument("--mode", choices=("skeleton", "contour"), default="skeleton")
    tr.add_argument("--threshold", type=float, default=None,
                    help="0~1；不给就用 Otsu 自动")
    tr.add_argument("--invert", action="store_true", help="亮的当墨（黑底线稿用）")
    tr.add_argument("--min-len", type=int, default=12, help="骨架模式：短于这个点数的线丢掉")
    tr.add_argument("--simplify", type=float, default=1.5, help="Douglas-Peucker 容差（像素）")
    tr.add_argument("--height", type=int, default=1000, help="输出画布高度")
    tr.add_argument("--max-lines", type=int, default=400)
    tr.add_argument("--ink", default="#3B342B", help="线的颜色")
    tr.add_argument("--width", type=float, default=5.0)
    tr.add_argument("--dilate", type=int, default=1,
                    help="骨架模式：先膨胀几圈补断口（0~3，默认 1）")
    tr.add_argument("--adaptive", type=int, default=0,
                    help="骨架模式：自适应阈值窗口（0=关，用全局阈值）")
    tr.add_argument("--adaptive-k", type=float, default=9.0,
                    help="比局部均值暗多少算墨（灰阶）")
    tr.add_argument("--join", type=float, default=5.0,
                    help="端点相距多少像素内就接上（默认 5）")

    pz = sub.add_parser("posterize",
                        help="图片 → 按颜色分层的场景（适合色块分明的插画/图标）")
    pz.add_argument("image")
    pz.add_argument("--out", default=None, help="输出场景（默认 scenes/<图名>.fyb）")
    pz.add_argument("--colors", type=int, default=24, help="量化成几种颜色")
    pz.add_argument("--blur", type=float, default=1.0,
                    help="量化前的模糊半径（压掉抗锯齿过渡带，0 = 不模糊）")
    pz.add_argument("--eps", type=float, default=1.8, help="轮廓简化容差（像素）")
    pz.add_argument("--height", type=int, default=1200, help="输出画布高度")
    pz.add_argument("--min-area", type=int, default=380, help="小于这个面积的色块丢掉")
    pz.add_argument("--win", type=int, default=7, help="多数表决窗口（去麻点）")

    bl = sub.add_parser("balance", help="构图体检：覆盖率网格 + 重心 + 空角")
    bl.add_argument("file")
    bl.add_argument("--cells", default="4x3", help="网格，默认 4x3（列x行）")
    bl.add_argument("--grid", choices=("thirds", "golden", "none"), default="thirds",
                    help="叠哪种构图线（默认三分）")
    bl.add_argument("--out", default=None, help="体检图输出路径")
    bl.add_argument("--no-png", action="store_true", help="只打文字，不出图")

    a = ap.parse_args(argv)
    path = Path(getattr(a, "file", None)
                or getattr(a, "target", None)
                or getattr(a, "image", None))
    if not path.exists():
        print(f"文件不存在：{path}", file=sys.stderr)
        return EXIT_DSL
    if a.cmd == "balance":
        try:
            c, r = str(a.cells).lower().split("x")
            cols, rows = max(2, min(8, int(c))), max(2, min(8, int(r)))
        except (ValueError, TypeError):
            cols, rows = 4, 3
        return cmd_balance(path, Path(a.out) if a.out else None,
                           cols, rows, a.grid, a.no_png)
    if a.cmd == "posterize":
        root = Path(__file__).resolve().parent.parent
        out = Path(a.out) if a.out else root / "scenes" / f"{path.stem}.fyb"
        return cmd_posterize(path, out, a.colors, a.blur, a.eps,
                             a.height, a.min_area, a.win)
    if a.cmd == "check":
        return cmd_check(path, a.json)
    if a.cmd == "render":
        out = Path(a.out) if a.out else path.with_suffix(".png")
        return cmd_render(path, out, a.scale, a.fast,
                          Path(a.ir) if a.ir else None, raw=a.raw,
                          under=Path(a.under) if a.under else None,
                          under_alpha=a.under_alpha)
    if a.cmd == "sweep":
        out = Path(a.out) if a.out else path.with_name(path.stem + "-sweep.png")
        return cmd_sweep(path, out, a.sets, a.cols, a.cell)
    if a.cmd == "feedback":
        tags = [t.strip() for t in a.tags.split(",") if t.strip()]
        return cmd_feedback(path, tags, a.apply)
    if a.cmd == "anim":
        out = Path(a.out) if a.out else path.with_suffix(".apng")
        return cmd_anim(path, out, a.frames, a.duration, a.scale)
    if a.cmd == "watch":
        root = Path(__file__).resolve().parent.parent
        out = Path(a.out) if a.out else root / "renders" / "_preview.png"
        status = Path(a.status) if a.status else root / ".state" / "preview.json"
        return cmd_watch(path, out, a.scale, a.settle, status)
    if a.cmd == "trace":
        out = Path(a.out) if a.out else path.with_name(path.stem + "-trace.fyb")
        return cmd_trace(path, out, a.mode, a.threshold, a.min_len, a.simplify,
                         a.height, a.max_lines, a.ink, a.width, a.invert,
                         a.dilate, a.join, a.adaptive, a.adaptive_k)
    return cmd_meta(path)


if __name__ == "__main__":
    raise SystemExit(main())
