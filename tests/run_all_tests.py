"""运行 tests/ 下全部 t_*.py（每小组独立子进程 + 超时，输出真实结果）。

用法（项目根目录）：
    .venv/Scripts/python.exe tests/run_all_tests.py
结果写入 tests/test_results.json。
"""
import glob
import json
import os
import subprocess
import sys
import time

PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
SKIP = {"t_triv.py", "t_com.py", "t_com2.py"}

venv_py = os.path.join(PROJ, ".venv", "Scripts", "python.exe")
PY = venv_py if os.path.exists(venv_py) else sys.executable
WORK = os.path.dirname(os.path.abspath(__file__))

files = sorted(f for f in os.listdir(WORK)
               if f.startswith("t_") and f.endswith(".py") and f not in SKIP)
files.sort(key=lambda f: os.path.getsize(os.path.join(WORK, f)))

results = []
env = dict(os.environ)
env.setdefault("PYTHONIOENCODING", "utf-8")
env.pop("QT_QPA_PLATFORM", None)

for f in files:
    t0 = time.time()
    try:
        p = subprocess.run([PY, f], cwd=WORK, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=900, env=env)
        out, code = (p.stdout or "") + (p.stderr or ""), p.returncode
    except subprocess.TimeoutExpired:
        out, code = "TIMEOUT", -9
    dt = time.time() - t0
    tail = [ln for ln in out.strip().splitlines() if ln.strip()][-3:]
    results.append({
        "file": f,
        "code": code,
        "seconds": round(dt, 1),
        "traceback": "Traceback (most recent call last)" in out,
        "tail": tail,
    })
    flag = "OK  " if code == 0 else "FAIL"
    print(f"[{flag}] {f:<24} {dt:5.1f}s  {tail[-1][:110] if tail else ''}", flush=True)

with open(os.path.join(WORK, "test_results.json"), "w", encoding="utf-8") as fh:
    json.dump(results, fh, ensure_ascii=False, indent=2)

bad = [r for r in results if r["code"] != 0]
print("\n%d 组：%d 通过，%d 失败，总耗时 %.0fs"
      % (len(results), len(results) - len(bad), len(bad), sum(r["seconds"] for r in results)))
for r in bad:
    print(f"\n--- {r['file']} (code={r['code']}, tb={r['traceback']}) ---")
    for ln in r["tail"]:
        print("   ", ln[:200])
sys.exit(0)
