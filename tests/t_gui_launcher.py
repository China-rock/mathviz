# -*- coding: utf-8 -*-
"""启动器 exe 的校验：无窗、能找到项目、能把 GUI 拉起来。

跑法：
    .venv\\Scripts\\python.exe C:\\Users\\ChRis\\mathviz_work\\t_gui_launcher.py

"无黑窗"不靠肉眼 —— 直接读 PE 头里的 Subsystem 字段：
    2 = WINDOWS_GUI（不分配控制台）
    3 = WINDOWS_CUI（会挂一个控制台，也就是双击闪黑窗的那种）
"""
from __future__ import annotations

import os
import struct
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(str(__import__("pathlib").Path(__file__).resolve().parents[1]))
EXE = ROOT / "MathViz.exe"
sys.path.insert(0, str(ROOT / "packaging"))

ok: list[str] = []


def pe_subsystem(path: Path) -> int:
    """读 PE Optional Header 的 Subsystem 字段。"""
    data = path.read_bytes()[:4096]
    assert data[:2] == b"MZ", "不是 PE 文件"
    e_lfanew = struct.unpack_from("<I", data, 0x3C)[0]
    assert data[e_lfanew:e_lfanew + 4] == b"PE\0\0", "PE 签名不对"
    coff = e_lfanew + 4
    opt_size = struct.unpack_from("<H", data, coff + 16)[0]
    opt = coff + 20
    magic = struct.unpack_from("<H", data, opt)[0]
    # PE32+ (0x20b) 的 Subsystem 在 0x44，PE32 (0x10b) 在 0x44 也一样
    assert magic in (0x10B, 0x20B), f"未知的 optional header magic: {magic:#x}"
    assert opt_size >= 0x46
    return struct.unpack_from("<H", data, opt + 0x44)[0]


# ---------- 1) 存在性与体积 ----------
assert EXE.is_file(), f"没有启动器: {EXE}"
size_mb = EXE.stat().st_size / 1048576
assert 2 < size_mb < 20, f"启动器 {size_mb:.1f} MB —— 太小不可能，太大说明把依赖打进去了"
ok.append(f"启动器 {size_mb:.1f} MB")

# ---------- 2) 无控制台 ----------
sub = pe_subsystem(EXE)
assert sub == 2, f"Subsystem={sub}（2=GUI 无黑窗，3=控制台会闪黑窗）"
ok.append("PE Subsystem=2（GUI 子系统，双击不弹黑窗）")

# ---------- 3) 未打包时也能定位项目根 ----------
import launcher  # noqa: E402

assert not getattr(sys, "frozen", False)

found = launcher.find_root()
assert found == ROOT, f"find_root 返回 {found}，应为 {ROOT}"
ok.append("未打包时定位到项目根")

# ---------- 4) 复制到别处时给出「找不到」而不是乱猜 ----------
import tempfile

with tempfile.TemporaryDirectory() as tmp:
    fake = Path(tmp) / "MathViz.exe"
    fake.write_bytes(b"MZ")
    real_exe = sys.executable
    had_frozen = hasattr(sys, "frozen")
    try:
        sys.frozen = True          # 模拟打包后
        sys.executable = str(fake)  # 假装 exe 被放到了别处
        got = launcher.find_root()
        assert got is None, f"exe 在临时目录却仍返回 {got} —— 会去启动错的程序"
    finally:
        if not had_frozen:
            del sys.frozen
        sys.executable = real_exe
ok.append("exe 被复制到别处时不乱猜（返回 None → 弹提示）")

# ---------- 5) 解释器指向 venv 的 pythonw ----------
py = launcher.find_python(ROOT)
assert py is not None and py.name.lower() == "pythonw.exe", f"解释器是 {py}"
assert str(py).lower().startswith(str(ROOT).lower()), f"{py} 不在项目里"
ok.append(f"解释器 = {py.parent.parent.parent.name}/.venv/Scripts/pythonw.exe")

# ---------- 6) 真启动：启动器秒退，GUI 在后头起来 ----------
# 不查进程列表：这台机器是 Win11，wmic 已被移除，而查进程命令行又要
# NtQueryInformationProcess 那一套。改看两样更硬的证据 ——
#   a) 项目 logs\console.log 新增了一条「MathViz 启动」（说明 app.main 真跑了）
#   b) 桌面上出现了标题含 MathViz 的可见窗口（说明 GUI 真画出来了）
import ctypes
from ctypes import wintypes

LOG = ROOT / "logs" / "console.log"
size_before = LOG.stat().st_size if LOG.is_file() else 0


def find_app_window() -> int:
    """返回标题含 MathViz 的可见顶层窗口句柄，没有则 0。"""
    user32 = ctypes.windll.user32
    found = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n > 0:
            buf = ctypes.create_unicode_buffer(n + 1)
            user32.GetWindowTextW(hwnd, buf, n + 1)
            if "MathViz" in buf.value:
                found.append((hwnd, buf.value))
                return False
        return True

    user32.EnumWindows(cb, 0)
    return found[0] if found else (0, "")


t0 = time.perf_counter()
proc = subprocess.Popen([str(EXE)], cwd=str(ROOT))
proc.wait(timeout=20)
elapsed = time.perf_counter() - t0
assert proc.returncode == 0, f"启动器退出码 {proc.returncode}"
assert elapsed < 5, f"启动器自己花了 {elapsed:.1f}s 才退出（没等 GUI）"
ok.append(f"启动器 {elapsed * 1000:.0f} ms 内退出（不常驻，不占内存）")

hwnd, title = 0, ""
for _ in range(60):                     # 最多等 60 秒
    hwnd, title = find_app_window()
    if hwnd:
        break
    time.sleep(1)
assert hwnd, "启动器退出了，但等 60 秒也没见到 MathViz 窗口 —— GUI 没起来"
ok.append(f"GUI 窗口已出现（标题「{title}」）")

grew = False
for _ in range(15):      # stdout 重定向到文件时是块缓冲，窗口先出来、日志后落盘
    if LOG.is_file() and LOG.stat().st_size > size_before:
        grew = True
        break
    time.sleep(1)
assert grew, "窗口有了但等了 15 秒日志也没新增 —— 不是我们启动的那个实例？"
ok.append("项目 logs\\console.log 新增启动记录")

# 收尾：发 WM_CLOSE 让它自己关（比 taskkill 温和，能走正常退出流程）
ctypes.windll.user32.PostMessageW(hwnd, 0x0010, 0, 0)
time.sleep(3)

print("PASS " + " | ".join(ok))
