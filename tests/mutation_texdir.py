"""变异测试：把定向纹理改回"钉在画布上"，确认 run_texdir.py 会失败。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "fyb" / "painter.py"
TESTS = ROOT / "tests" / "run_texdir.py"

OLD = """            ang = _mean_angle(pts)
            k = tex_scale * scale
            t = QTransform()
            t.translate((pts[0][0] - x0) * scale, (pts[0][1] - y0) * scale)
            t.rotate(ang)
            t.scale(k, k)
            brush = QBrush(tile)
            brush.setTransform(t)"""

NEW = """            brush = QBrush(tile.scaled(max(1, int(tile.width() * tex_scale * scale)),
                                       max(1, int(tile.height() * tex_scale * scale)),
                                       Qt.IgnoreAspectRatio, Qt.SmoothTransformation))"""


def main() -> int:
    orig = MOD.read_text(encoding="utf-8")
    if OLD not in orig:
        print("[!] 找不到锚点")
        return 1
    try:
        MOD.write_text(orig.replace(OLD, NEW), encoding="utf-8")
        r = subprocess.run([sys.executable, str(TESTS)], capture_output=True,
                           text=True, encoding="utf-8", errors="replace")
        out = r.stdout or ""
        caught = r.returncode != 0
        print("[%s] 改回画布空间后，测试%s" % ("ok" if caught else "!!",
                                              "失败（守卫有效）" if caught else "仍然通过"))
        for line in out.splitlines():
            if line.startswith("FAIL") or "笔" in line:
                print("     " + line.strip()[:70])
        return 0 if caught else 1
    finally:
        MOD.write_text(orig, encoding="utf-8")
        print("已还原 painter.py")


if __name__ == "__main__":
    raise SystemExit(main())
