"""一键打包：主程序 + manim_worker，最后并到同一个目录里。

用法（项目根目录）：
    .venv\\Scripts\\python.exe packaging\\build_all.py

为什么是两个 exe 而不是一个，见 MathViz.spec 顶部的说明。这里额外解释一句
"为什么要搬"：PyInstaller 的 onedir 输出会整个清掉目标目录，两次构建不能指向
同一个 dist\\MathViz，否则第二次会把第一次删掉。所以各自出各自的，再合起来。
"""
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = ROOT / ".venv" / "Scripts" / "python.exe"
DIST = ROOT / "dist"
OUT = DIST / "MathViz"
WORKER_BUILD = DIST / "MathViz_worker"
CONTENTS_WORKER = "_internal_worker"      # 与主程序的 _internal 分开，互不覆盖


def run(*args):
    print(f"\n>>> {' '.join(str(a) for a in args)}")
    t = time.time()
    r = subprocess.run([str(a) for a in args], cwd=str(ROOT))
    if r.returncode != 0:
        sys.exit(f"构建失败（退出码 {r.returncode}）")
    print(f"<<< 用时 {time.time() - t:.0f}s")


def size_mb(path: Path) -> float:
    if path.is_file():
        return path.stat().st_size / 1048576
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file()) / 1048576


def move_aside(path: Path):
    """把旧产物改名让位，而不是删除。

    PyInstaller 出 onedir 时会先删掉同名目录，批量删除容易触发安全确认；
    改名成本一样、可回退，旧目录留着手动删就行。
    """
    if not path.exists():
        return
    dst = path.with_name(f"{path.name}_old_{time.strftime('%m%d_%H%M%S')}")
    try:
        os.rename(path, dst)
        print(f"（旧产物已让位：{path.name} → {dst.name}，确认无误后可手动删除）")
    except OSError as e:
        print(f"（无法移开 {path.name}：{e}）")


def main():
    move_aside(OUT)
    move_aside(WORKER_BUILD)

    run(PY, "-m", "PyInstaller", "packaging/MathViz.spec", "--noconfirm",
        "--distpath", DIST, "--workpath", ROOT / "build")
    # 依赖目录改名写在 spec 里（--contents-directory 不能和 spec 一起用）
    run(PY, "-m", "PyInstaller", "packaging/manim_worker.spec", "--noconfirm",
        "--distpath", DIST, "--workpath", ROOT / "build")

    # 合并：worker 的 exe 与它的依赖目录一起搬进主程序目录
    if not OUT.exists():
        sys.exit(f"主程序产物缺失：{OUT}")
    worker_exe = WORKER_BUILD / "manim_worker.exe"
    worker_dir = WORKER_BUILD / CONTENTS_WORKER
    for src in (worker_exe, worker_dir):
        if not src.exists():
            sys.exit(f"worker 产物缺失：{src}")
    shutil.copy2(worker_exe, OUT / "manim_worker.exe")
    if (OUT / CONTENTS_WORKER).exists():
        shutil.rmtree(OUT / CONTENTS_WORKER)
    shutil.copytree(worker_dir, OUT / CONTENTS_WORKER)
    shutil.rmtree(WORKER_BUILD)

    print("\n=== 打包完成 ===")
    print(f"产物目录：{OUT}（{size_mb(OUT):.0f} MB）")
    for name in ("MathViz.exe", "manim_worker.exe"):
        p = OUT / name
        print(f"  {'✔' if p.exists() else '✘'} {name}  "
              f"{size_mb(p):.1f} MB" if p.exists() else f"  ✘ {name} 缺失")
    print(f"  依赖目录：_internal（{size_mb(OUT / '_internal'):.0f} MB）、"
          f"{CONTENTS_WORKER}（{size_mb(OUT / CONTENTS_WORKER):.0f} MB）")
    print("\n自测：双击 MathViz.exe，或直接跑一次渲染验证 worker 可用。")


if __name__ == "__main__":
    main()
