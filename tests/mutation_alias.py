"""变异测试：把别名层去掉，确认 run_alias.py 会红。"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MOD = ROOT / "fyb" / "parser.py"
TESTS = ROOT / "tests" / "run_alias.py"

OLD = """            alias = aliases_for(spec.keys)
            key = alias.get(key, key)"""
NEW = """            alias = {}
            key = key"""


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
        fails = [ln for ln in out.splitlines() if ln.startswith("FAIL")]
        print("[%s] 去掉别名层后测试%s，%d 条抓到"
              % ("ok" if caught else "!!", "失败" if caught else "仍通过", len(fails)))
        for ln in fails[:4]:
            print("     " + ln.strip()[:64])
        return 0 if caught else 1
    finally:
        MOD.write_text(orig, encoding="utf-8")
        print("已还原 parser.py")


if __name__ == "__main__":
    raise SystemExit(main())
