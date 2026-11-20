"""变异测试：让 posterize 的两处关键逻辑失效，确认 run_posterize.py 会失败。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "fyb" / "posterize.py"
TESTS = ROOT / "tests" / "run_posterize.py"

MUTATIONS = [
    ("不跳过背景",
     """            if (xs.min() <= 2 and xs.max() >= iw - 3
                    and ys.min() <= 2 and ys.max() >= ih - 3):
                continue""",
     "            pass"),
    ("不做多数表决去噪",
     "    labels = clean_labels(np.asarray(q).astype(np.uint8), colors, win=win)",
     "    labels = np.asarray(q).astype(np.uint8)"),
]


def run():
    r = subprocess.run([sys.executable, str(TESTS)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "")


def main() -> int:
    orig = MOD.read_text(encoding="utf-8")
    caught = 0
    try:
        for name, old, new in MUTATIONS:
            if old not in orig:
                print("[!] %s: 锚点没找到" % name)
                continue
            MOD.write_text(orig.replace(old, new), encoding="utf-8")
            code, out = run()
            fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
            if code != 0:
                caught += 1
                print("[ok] %s -> 测试失败，%d 条抓到" % (name, len(fails)))
                for ln in fails[:2]:
                    print("       " + ln.strip()[:60])
            else:
                print("[!!] %s -> 测试仍然通过" % name)
    finally:
        MOD.write_text(orig, encoding="utf-8")
        print("已还原 posterize.py")
    return 0 if caught == len(MUTATIONS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
