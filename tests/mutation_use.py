"""变异测试：把三个修复分别撤销，确认 run_use.py 真的会失败。

不这么验一遍，那 17 条断言只是"看起来在守着"。
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RES = ROOT / "fyb" / "resolve.py"
TESTS = ROOT / "tests" / "run_use.py"

MUTATIONS = [
    ("撤销 grad 深拷贝",
     "clone.grad = dict(prim.grad) if prim.grad else {}",
     "clone.grad = prim.grad"),
    ("撤销 p0/p1 变换",
     '    if clone.grad.get("p0") is not None:\n'
     '        clone.grad["p0"] = apply(m, *clone.grad["p0"])\n'
     '    if clone.grad.get("p1") is not None:\n'
     '        clone.grad["p1"] = apply(m, *clone.grad["p1"])',
     "    pass"),
    ("撤销 mate 清零",
     "                    if old_ref in remap:\n"
     "                        clone.mate = None",
     "                    pass"),
]


def run_tests():
    r = subprocess.run([sys.executable, str(TESTS)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "")


def main() -> int:
    orig = RES.read_text(encoding="utf-8")
    caught = 0
    try:
        for name, old, new in MUTATIONS:
            if old not in orig:
                print("[!] %s: 找不到锚点（代码变了？）" % name)
                continue
            RES.write_text(orig.replace(old, new), encoding="utf-8")
            code, out = run_tests()
            fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
            if code != 0:
                caught += 1
                print("[ok] %s -> 测试失败，%d 条断言抓到" % (name, len(fails)))
                for ln in fails[:3]:
                    print("       " + ln.strip()[:64])
            else:
                print("[!!] %s -> 测试仍然通过，说明这条守卫没用" % name)
    finally:
        RES.write_text(orig, encoding="utf-8")
        print("已还原 resolve.py")
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
