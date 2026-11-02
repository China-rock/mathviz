"""Manim 渲染器：子进程调用 venv 内的 manim CLI。

关键设计：
- 工作目录固定在无空格路径（config.RENDER_WORK_DIR），绕开 LaTeX 对空格路径的兼容问题。
- ffmpeg 不在系统 PATH：从 imageio_ffmpeg 提取内置二进制所在目录，注入子进程 PATH。
- 实时逐行回传日志（log_cb），界面滚动显示。
- 渲染成功后可调用 probe_video() 做成片体检（黑屏 / 静帧 / 时长），提前发现"看着不对"的视频。
"""
import contextlib
import math
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path

from . import texenv
from .config import (OUTPUT_MEDIA_DIR, RENDER_MEDIA_DIR, RENDER_WORK_DIR)

RENDER_TIMEOUT_SECONDS = 900

# 子进程一律不许弹控制台窗口。
# 主进程用 pythonw.exe 启动时本身没有窗口，但从无窗口父进程 fork 出来的
# 控制台子进程会自己去申请一个新控制台 —— 表现就是渲染时"黑窗一闪一闪"。
# CREATE_NO_WINDOW 显式禁止这件事（Windows 专有，其他平台为 0）。
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# 上面那句只管得住"我们直接 fork 的那一层"（manim 本身）。
# manim 在渲染时还会自己 spawn pdflatex / dvisvgm / ffmpeg，那些孙辈进程默认开窗。
# 解法：把这个目录塞进子进程的 PYTHONPATH，里面的 sitecustomize.py 会在
# manim 那个解释器启动时被自动 import，从内部改掉 subprocess.Popen 的默认 flags。
_NOWINDOW_SITE_DIR = str(Path(__file__).resolve().parent / "_nowindow")

# Windows 文件名非法字符（其他平台也不该出现在文件名里）
_ILLEGAL_CHARS = r'<>:"/\|?*'


class RenderError(Exception):
    pass


def safe_stem(text: str, limit: int = 40) -> str:
    """把任意标题整理成安全的文件名主干。

    - 去掉 Windows 非法字符（\\ / : * ? " < > |）与控制字符
    - 压缩空白为单个空格（标题里常见的全角空格也一并处理）
    - 超长截断；空结果回落到 Untitled
    """
    cleaned = "".join(
        " " if (ch.isspace() or ord(ch) < 32) else ("" if ch in _ILLEGAL_CHARS else ch)
        for ch in (text or "")
    ).strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    if not cleaned:
        return "Untitled"
    return cleaned[:limit].rstrip(" .")


# 高清成片的命名前缀（放在文件名最前面，一眼区分 480p 预览与 1080p 成片）
HD_PREFIX = "[HD] "

# 非横屏画幅的命名前缀：同一个知识点横竖各渲一支时，靠文件名就能分清
_LAYOUT_PREFIX = {"9:16": "[竖] ", "1:1": "[方] "}

# 可选画幅（宽:高）。
LAYOUTS: dict[str, tuple[int, int]] = {
    "16:9": (16, 9),
    "9:16": (9, 16),
    "1:1": (1, 1),
}

# 质量档位：短边像素 + 帧率。三档直接对应 manim 的预设
# -ql(480p15) / -qm(720p30) / -qh(1080p60) —— 16:9 走预设，其他画幅按短边换算。
QUALITIES: dict[str, tuple[int, int]] = {
    "low": (480, 15),
    "medium": (720, 30),
    "high": (1080, 60),
}
QUALITY_FLAGS = {"low": "-ql", "medium": "-qm", "high": "-qh"}
QUALITY_LABELS = {"low": "480p", "medium": "720p", "high": "1080p"}


def quality_short_side(quality: str) -> int:
    return QUALITIES.get((quality or "").strip(), QUALITIES["low"])[0]


def quality_fps(quality: str) -> int:
    return QUALITIES.get((quality or "").strip(), QUALITIES["low"])[1]


def resolution_for(layout: str, quality: str) -> tuple[int, int] | None:
    """画幅 + 质量 -> 像素 (宽, 高)。未知画幅返回 None（回落 manim 预设）。

    用向上取整对齐 manim 的预设口径（480p 横屏是 854x480，不是 853x480）。
    """
    ratio = LAYOUTS.get((layout or "").strip())
    if not ratio:
        return None
    wr, hr = ratio
    short = quality_short_side(quality)
    if wr <= hr:      # 竖屏 / 方形：短边是宽
        w, h = short, math.ceil(short * hr / wr)
    else:
        w, h = math.ceil(short * wr / hr), short
    # h264 只认偶数尺寸 —— 奇数像素会让 ffmpeg 直接拒绝编码
    return w + (w & 1), h + (h & 1)


def archive_filename(stem: str, suffix: str = ".mp4", prefix: str = "") -> str:
    """成片归档名：`<前缀><知识点名>-<HHMMSS>.mp4`。

    斜杠/冒号不能进文件名（Windows 会直接判定路径非法），因此时、分、秒
    连写成 HHMMSS。同名文件（同一秒内重复渲染）自动追加序号，绝不覆盖旧片。
    prefix 目前只用于高清成片的 "[HD] " 标记。
    """
    base = f"{prefix}{safe_stem(stem)}-{time.strftime('%H%M%S')}"
    target = OUTPUT_MEDIA_DIR / f"{base}{suffix}"
    n = 2
    while target.exists():
        target = OUTPUT_MEDIA_DIR / f"{base}_{n}{suffix}"
        n += 1
    return target.name


def _ffmpeg_dir() -> str | None:
    try:
        import imageio_ffmpeg
        return str(Path(imageio_ffmpeg.get_ffmpeg_exe()).parent)
    except Exception:
        return None


# LaTeX 目录探测统一放在 texenv 里（打包版还要拿它做"缺环境"的引导提示），
# 这里直接用，避免两处候选路径各写一份、改一个漏一个。


def _manim_base_cmd() -> list[str]:
    """manim 的调用前缀 —— 打包后这里必须换人。

    开发环境是 `[python, "-m", "manim"]`。打成 exe 之后（sys.frozen）解释器
    被冻结，不再接受 `-m`，`MathViz.exe -m manim` 只会照常弹出界面、渲染静默
    失败，所以必须改成同目录里那个独立的 manim_worker.exe（由 PyInstaller
    用同一个依赖树打出来的第二个入口）。
    """
    if getattr(sys, "frozen", False):
        worker = Path(sys.executable).with_name("manim_worker.exe")
        if worker.exists():
            return [str(worker)]
        # worker 缺失时仍然退到 -m：会失败，但日志里能一眼看出是打包漏了文件
    return [sys.executable, "-m", "manim"]


def _build_env(log) -> dict:
    """manim 子进程的环境变量：补 ffmpeg / latex 目录、静音补丁、统一编码。

    单独抽出来是因为「正式渲染」与「版式快检」都要用，且这两处的补丁
    缺任何一项都会以一种很难懂的方式失败（黑窗 / 找不到 latex / 中文乱码）。
    """
    env = os.environ.copy()
    extra_dirs = []
    ffmpeg_dir = _ffmpeg_dir()
    if ffmpeg_dir:
        extra_dirs.append(ffmpeg_dir)
    latex_dir = texenv.latex_dir()
    if latex_dir:
        extra_dirs.append(latex_dir)
        log(f"[环境] PATH 中未找到 latex，已自动补充 MiKTeX: {latex_dir}")
    if extra_dirs:
        env["PATH"] = os.pathsep.join(extra_dirs) + os.pathsep + env.get("PATH", "")
    env["PYTHONIOENCODING"] = "utf-8"
    # 注入"子进程静默"补丁（sitecustomize 会被解释器自动导入）
    env["PYTHONPATH"] = os.pathsep.join(
        p for p in (_NOWINDOW_SITE_DIR, env.get("PYTHONPATH", "")) if p)
    return env


def _scene_class_names(code: str) -> list[str]:
    import ast
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    return [n.name for n in ast.walk(tree)
            if isinstance(n, ast.ClassDef) and any(
                isinstance(b, ast.Name) and b.id in ("Scene", "ThreeDScene")
                for b in n.bases)]


def count_plays(code: str) -> int:
    """数一遍脚本里 self.play / self.wait 的调用个数（= manim 的"动画段"数）。

    只做静态计数：写在 for 里的调用按 1 次算，而 manim 运行时会按实际迭代次数递增。
    所以对含循环脚本，这个数只用来给「分段渲染」提供范围上限，不追求精确。
    语法错误返回 0（调用方据此禁用分段）。
    """
    import ast
    try:
        tree = ast.parse(code or "")
    except SyntaxError:
        return 0
    n = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("play", "wait"):
            n += 1
    return n


# manim 的进度是"逐动画"打的（Animation 3: ... 60%|###|），没有全局百分比。
# 用 Animation 序号 + 该动画内的百分比，配合 count_plays 估出的总数换算成总体进度。
_PROG_RE = re.compile(r"(\d{1,3})%\|")
_ANIM_RE = re.compile(r"Animation (\d+):")


# 正在跑的渲染进程。退出程序时要靠它把 manim（以及它下面的 latex、dvisvgm）一起收掉。
_ACTIVE_PROCS: set = set()
_PROCS_LOCK = threading.Lock()


def _register(proc) -> None:
    with _PROCS_LOCK:
        _ACTIVE_PROCS.add(proc)


def _unregister(proc) -> None:
    with _PROCS_LOCK:
        _ACTIVE_PROCS.discard(proc)


def active_count() -> int:
    """当前有几个 manim 进程还活着。

    关窗口前用它判断"是不是正在渲染"。不能只看 QThread 的 isRunning()：
    批量渲染两支之间、以及启动 manim 之前的空档，线程活着但进程还没起来。
    """
    with _PROCS_LOCK:
        return sum(1 for p in _ACTIVE_PROCS if p.poll() is None)


def terminate_active() -> int:
    """退出程序前调用：杀掉还在跑的渲染进程，返回处理了几个。

    不做这件事的话，用户关掉窗口后 manim 仍在后台跑：占满 CPU、占着
    `media` 目录，下次渲染直接报文字体/文件被占用。Windows 上还得用
    `taskkill /T` 连子进程一起杀 —— terminate() 只结束 manim 本身，
    它拉起的 latex、dvisvgm 会变成孤儿继续跑。
    """
    with _PROCS_LOCK:
        procs = [p for p in _ACTIVE_PROCS if p.poll() is None]
    for p in procs:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)],
                               capture_output=True, timeout=10,
                               creationflags=_NO_WINDOW)
            else:
                p.terminate()
        except Exception:
            with contextlib.suppress(Exception):
                p.kill()
    with _PROCS_LOCK:
        _ACTIVE_PROCS.clear()
    return len(procs)


def _pump_and_wait(proc, log, timeout: int) -> bool:
    """一边读 stdout 一边等进程结束；超时就杀掉。返回 True 表示超时。

    顺序是关键：直接 `for raw in proc.stdout` 会在进程卡住（既不输出、也不退出，
    比如 LaTeX 在等输入、字体缓存被别的进程占着）时永远阻塞，后面的
    wait(timeout) 根本执行不到 —— 超时形同虚设，界面会一直停在"渲染中"，
    用户只能强杀程序。所以读输出必须丢到独立线程里，主线程负责计时。
    """
    def _pump():
        try:
            for raw in proc.stdout or ():
                log(raw.rstrip())
        except Exception:
            pass            # 被 kill 之后管道关闭，读端会抛，忽略即可

    reader = threading.Thread(target=_pump, daemon=True)
    _register(proc)
    reader.start()
    try:
        try:
            proc.wait(timeout=timeout)
            reader.join(timeout=5)
            return False
        except subprocess.TimeoutExpired:
            with contextlib.suppress(Exception):
                proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=5)        # 收尸，别留僵尸进程
            reader.join(timeout=5)
            return True
    finally:
        _unregister(proc)


def render(code: str, scene_name: str, quality: str = "low",
           log_cb=None, archive_stem: str | None = None,
           layout: str = "16:9", anim_range: tuple[int, int] | None = None,
           progress_cb=None) -> tuple[bool, Path | None, str]:
    """渲染一段脚本。quality: "low" / "medium" / "high"；layout: "16:9" / "9:16" / "1:1"。

    archive_stem: 归档成片的文件名主干，通常传知识点标题；
                  省略则用 scene_name。
    anim_range:   只渲染第 a~b 段（manim 的 -n a,b，闭区间、1 起数）。
                  前面的段会被"瞬间跑完"（画面直接到位），因此成片只含选中那几段。
    progress_cb:  收到 0~100 的整数百分比（估算值），用于状态栏进度条。
    16:9 走 manim 的 -ql/-qm/-qh 预设（与历史行为完全一致）；
    竖屏/方形用 -r W,H 显式指定分辨率（短边对齐质量档，fps 同质量档）。
    返回 (ok, mp4_path 或 None, 合并日志)。
    """
    RENDER_WORK_DIR.mkdir(parents=True, exist_ok=True)
    RENDER_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    OUTPUT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    scenes_dir = RENDER_WORK_DIR / "scenes"
    scenes_dir.mkdir(exist_ok=True)
    script_path = scenes_dir / f"{scene_name}.py"
    script_path.write_text(code, encoding="utf-8")

    layout = (layout or "").strip()
    rel_script = f"scenes/{script_path.name}"
    if layout in ("", "16:9"):
        flag = QUALITY_FLAGS.get(quality, "-ql")
        cmd = [*_manim_base_cmd(), flag,
               "--media_dir", str(RENDER_MEDIA_DIR),
               rel_script, scene_name]
        flag_desc = flag
    else:
        res = resolution_for(layout, quality)
        if res is None:
            return False, None, f"[错误] 不支持的画幅：{layout}"
        fps = str(quality_fps(quality))
        cmd = [*_manim_base_cmd(),
               "-r", f"{res[0]},{res[1]}", "--fps", fps,
               "--media_dir", str(RENDER_MEDIA_DIR),
               rel_script, scene_name]
        flag_desc = f"-r {res[0]}x{res[1]}@{fps}fps"
    if anim_range:
        a, b = int(anim_range[0]), int(anim_range[1])
        if a < 1:
            a = 1
        if b < a:
            b = a
        cmd += ["-n", f"{a},{b}"]
        flag_desc += f" 第{a}~{b}段"

    lines: list[str] = []
    total_plays = count_plays(code) or 0
    _prog = {"anim": 0, "last": -1}

    def log(msg: str):
        lines.append(msg)
        if log_cb:
            log_cb(msg)
        if progress_cb and total_plays:
            m = _ANIM_RE.search(msg)
            if m:
                _prog["anim"] = int(m.group(1))
            pcts = _PROG_RE.findall(msg)
            if pcts:
                try:
                    frac = min(100, int(pcts[-1])) / 100.0
                except ValueError:
                    return
                overall = int((_prog["anim"] + frac) / total_plays * 100)
                overall = max(0, min(99, overall))
                if overall > _prog["last"]:
                    _prog["last"] = overall
                    progress_cb(overall)

    log(f"[渲染] manim {flag_desc} {scene_name} （工作目录: {RENDER_WORK_DIR}）")
    env = _build_env(log)
    start = time.time()
    try:
        proc = subprocess.Popen(
            cmd, cwd=RENDER_WORK_DIR, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:
        return False, None, "\n".join(lines + [f"[错误] 无法启动渲染进程: {e}"])

    if _pump_and_wait(proc, log, RENDER_TIMEOUT_SECONDS):
        return False, None, "\n".join(
            lines + [f"[错误] 渲染超时（>{RENDER_TIMEOUT_SECONDS}s，已终止渲染进程）"])

    elapsed = time.time() - start
    output = "\n".join(lines)
    mp4 = _find_latest_mp4(scene_name)
    if proc.returncode == 0 and mp4:
        # 归档到项目 media/ 目录，文件名 = 知识点标题 + 时分秒
        # （高清加 [HD]、竖屏加 [竖]、方形加 [方]，一眼分清是哪一版）
        prefix = (HD_PREFIX if quality == "high" else "") \
            + _LAYOUT_PREFIX.get(layout, "")
        stem = archive_stem or scene_name
        if anim_range:
            stem = f"{stem}-第{anim_range[0]}-{anim_range[1]}段"
        dest = OUTPUT_MEDIA_DIR / archive_filename(stem, prefix=prefix)
        try:
            shutil.copy2(mp4, dest)
        except Exception:
            dest = mp4
        log(f"[完成] 用时 {elapsed:.0f}s -> {dest}")
        if progress_cb:
            progress_cb(100)
        return True, dest, output
    if progress_cb:
        progress_cb(100)
    return False, None, output


# ------------------------------------------------------------------ 版式快检

# 快检产物单独放一个目录：它渲出来的低帧率片子不是"成片"，
# 混进 RENDER_MEDIA_DIR 会被 _find_latest_mp4 当成最新的正式成片捡走。
QC_MEDIA_DIR = RENDER_WORK_DIR / "quickcheck_media"
QC_FRAME_DIR = RENDER_WORK_DIR / "quickcheck"

# 快检用的参数：帧率砍到 5、短边 360px，只为看清"字压没压在一起"，
# 代价是画面糊、播放卡顿 —— 所以它只出定格图，不出可播放的片子。
QC_FPS = 5
QC_SHORT_SIDE = 360


def qc_resolution_for(layout: str) -> tuple[int, int]:
    """快检分辨率：保持画幅比例，短边固定 360。"""
    wr, hr = LAYOUTS.get((layout or "").strip(), (16, 9))
    if wr <= hr:
        w, h = QC_SHORT_SIDE, math.ceil(QC_SHORT_SIDE * hr / wr)
    else:
        w, h = math.ceil(QC_SHORT_SIDE * wr / hr), QC_SHORT_SIDE
    return w + (w & 1), h + (h & 1)


def render_quickcheck(code: str, scene_name: str, layout: str = "16:9",
                      frames: int = 6, log_cb=None,
                      progress_cb=None) -> tuple[bool, Path | None, str]:
    """版式快检：极低帧率 + 小分辨率跑一遍，从中抽 N 张定格供人眼看版式。

    为什么不直接完整渲染：一支 45 秒的片子完整渲要一两分钟，
    而"文字压成一团"这类问题在成片出来之前没人知道。快检把帧率砍到 1/3、
    像素砍到 1/4，同样的画面布局几秒到十几秒就能看见，
    改完再正式渲，省掉的是整支片子的等待。

    返回 (ok, 帧目录 或 None, 说明)。帧目录里的 PNG 按时序编号。
    """
    RENDER_WORK_DIR.mkdir(parents=True, exist_ok=True)
    QC_MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    QC_FRAME_DIR.mkdir(parents=True, exist_ok=True)

    scenes_dir = RENDER_WORK_DIR / "scenes"
    scenes_dir.mkdir(exist_ok=True)
    script_path = scenes_dir / f"{scene_name}.py"
    script_path.write_text(code, encoding="utf-8")

    layout = (layout or "").strip()
    w, h = qc_resolution_for(layout)
    cmd = [*_manim_base_cmd(),
           "-r", f"{w},{h}", "--fps", str(QC_FPS),
           "--media_dir", str(QC_MEDIA_DIR),
           f"scenes/{script_path.name}", scene_name]

    lines: list[str] = []

    def log(msg: str):
        lines.append(msg)
        if log_cb:
            log_cb(msg)
        if progress_cb:
            pcts = _PROG_RE.findall(msg)
            if pcts:
                try:
                    progress_cb(max(0, min(95, int(pcts[-1]))))
                except ValueError:
                    pass

    log(f"[快检] {w}x{h}@{QC_FPS}fps（只为看版式，不是成片）")
    start = time.time()
    try:
        proc = subprocess.Popen(
            cmd, cwd=RENDER_WORK_DIR, env=_build_env(log),
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1,
            creationflags=_NO_WINDOW,
        )
    except Exception as e:
        return False, None, "\n".join(lines + [f"[错误] 无法启动快检: {e}"])

    if _pump_and_wait(proc, log, RENDER_TIMEOUT_SECONDS):
        return False, None, "\n".join(lines + ["[错误] 快检超时（已终止渲染进程）"])

    if proc.returncode != 0:
        return False, None, "\n".join(lines)
    mp4 = _find_latest_in(QC_MEDIA_DIR, scene_name)
    if not mp4:
        # 兜底：脚本里的 Scene 类名与传入的 scene_name 不一致时（手工改过类名），
        # 按文件名匹配会落空。快检目录里只会有一支刚渲完的片子，取最新的即可。
        leftovers = sorted(QC_MEDIA_DIR.rglob("*.mp4"), key=lambda p: p.stat().st_mtime)
        mp4 = leftovers[-1] if leftovers else None
        if mp4:
            log(f"[快检] 未按 {scene_name} 匹配到文件，改用目录里最新的一支：{mp4.name}")
    if not mp4:
        return False, None, "\n".join(lines + ["[错误] 快检没产出视频"])

    dest = QC_FRAME_DIR / f"{safe_stem(scene_name)}-{time.strftime('%H%M%S')}"
    ok, _p, msg = export_frames(mp4, archive_stem=scene_name, count=frames,
                                log_cb=log, dest_dir=dest)
    elapsed = time.time() - start
    # 这片子帧率低到没法看，留着只会占地方（抽完帧就没用了）
    try:
        mp4.unlink()
    except Exception:
        pass
    if not ok:
        return False, None, "\n".join(lines + [f"[错误] 抽帧失败：{msg}"])
    log(f"[快检] 用时 {elapsed:.0f}s，{frames} 张定格 -> {dest}")
    if progress_cb:
        progress_cb(100)
    return True, dest, f"用时 {elapsed:.0f}s · {msg}"


def _find_latest_in(root: Path, name_hint: str) -> Path | None:
    cands = [p for p in root.rglob("*.mp4") if name_hint in p.name]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def _ffmpeg_exe() -> str | None:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def export_gif(mp4_path, archive_stem: str | None = None, fps: int = 10,
               width: int = 480, max_seconds: float = 20.0,
               log_cb=None) -> tuple[bool, Path | None, str]:
    """把成片转成 GIF（插 PPT / 微信 / 课件用）。

    GIF 天生臃肿：这里做了三重克制 —— 降帧率到 10、宽度压到 480px、
    超过 max_seconds 秒只取前面一段。否则几十秒的教学片能转出上百 MB。
    走 palettegen → paletteuse 两遍法，色彩过渡才不糊。
    """
    src = Path(mp4_path)
    exe = _ffmpeg_exe()
    if exe is None:
        return False, None, "找不到 ffmpeg（依赖 imageio-ffmpeg），无法转 GIF"
    if not src.exists():
        return False, None, f"源文件不存在：{src}"
    OUTPUT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    stem = archive_stem or src.stem
    dest = OUTPUT_MEDIA_DIR / archive_filename(stem, suffix=".gif")
    palette = dest.with_suffix(".palette.png")
    vf = f"fps={fps},scale={width}:-1:flags=lanczos"
    common = [exe, "-y", "-ss", "0"]
    if max_seconds:
        common += ["-t", str(max_seconds)]
    try:
        p = subprocess.run(
            common + ["-i", str(src), "-vf", f"{vf},palettegen", str(palette)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
            timeout=180)
        if p.returncode != 0 or not palette.exists():
            return False, None, (p.stdout or "")[-400:] or "调色板生成失败"
        if log_cb:
            log_cb("[GIF] 调色板已生成，正在合成……")
        p2 = subprocess.run(
            common + ["-i", str(src), "-i", str(palette), "-filter_complex",
                      f"{vf}[x];[x][1:v]paletteuse", str(dest)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
            encoding="utf-8", errors="replace", creationflags=_NO_WINDOW,
            timeout=300)
        if p2.returncode != 0 or not dest.exists():
            return False, None, (p2.stdout or "")[-400:] or "GIF 合成失败"
        size_mb = dest.stat().st_size / 1024 / 1024
        msg = f"[GIF] {dest.name}（{size_mb:.1f} MB）"
        if log_cb:
            log_cb(msg)
        return True, dest, msg
    except Exception as e:
        return False, None, f"转 GIF 失败：{e}"
    finally:
        try:
            if palette.exists():
                palette.unlink()
        except Exception:
            pass


def video_duration(mp4_path) -> float | None:
    """读视频时长（秒）。本机能装的可能只有 imageio 自带的 ffmpeg，
    没有独立 ffprobe，所以直接吃 `ffmpeg -i` 的 stderr 里的 Duration 行。"""
    exe = _ffmpeg_exe()
    if exe is None:
        return None
    try:
        r = subprocess.run([exe, "-hide_banner", "-i", str(mp4_path)],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="ignore", timeout=120,
                           creationflags=_NO_WINDOW)
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", r.stderr)
        if not m:
            return None
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    except Exception:
        return None


def export_frames(mp4_path, archive_stem: str | None = None,
                  count: int = 12, log_cb=None,
                  dest_dir=None) -> tuple[bool, Path | None, str]:
    """从成片里等间隔抽 N 张关键帧 PNG（做插图、印讲义、逐帧讲解用）。

    为什么不走 manim 的 --format=png：那条路会重新渲染一遍（慢），
    而且输出的是每帧一张（一分钟片子几千张），既没筛也没名。
    从已生成的视频抽帧既快又可控，还保证和你看到的成片完全一致。
    """
    src = Path(mp4_path)
    exe = _ffmpeg_exe()
    if exe is None:
        return False, None, "找不到 ffmpeg（依赖 imageio-ffmpeg），无法抽帧"
    if not src.exists():
        return False, None, f"源文件不存在：{src}"
    OUTPUT_MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    duration = video_duration(src)
    if not duration or duration <= 0:
        return False, None, "读不出视频时长，无法抽帧"

    stem = archive_stem or src.stem
    if dest_dir:
        dest = Path(dest_dir)
    else:
        dest = OUTPUT_MEDIA_DIR / f"{safe_stem(stem)}-{time.strftime('%H%M%S')}-关键帧"
    dest.mkdir(parents=True, exist_ok=True)
    made = 0
    for i in range(count):
        # 取每段的中间点，避开转场瞬间那两帧黑屏
        t = duration * (i + 0.5) / count
        out_png = dest / f"{i + 1:03d}.png"
        try:
            r = subprocess.run(
                [exe, "-y", "-ss", f"{t:.2f}", "-i", str(src),
                 "-frames:v", "1", "-q:v", "2", str(out_png)],
                capture_output=True, text=True, encoding="utf-8",
                errors="ignore", timeout=120, creationflags=_NO_WINDOW)
            if r.returncode == 0 and out_png.exists():
                made += 1
        except Exception:
            pass
        if log_cb and i % 4 == 0:
            log_cb(f"[PNG] 抽帧 {i + 1}/{count}……")
    if not made:
        return False, None, "一帧都没抽出来"
    msg = f"[PNG] {made} 张关键帧 -> {dest.name}"
    if log_cb:
        log_cb(msg)
    return True, dest, msg


def _find_latest_mp4(scene_name: str) -> Path | None:
    cands = [p for p in RENDER_MEDIA_DIR.rglob("*.mp4") if scene_name in p.name]
    if not cands:
        return None
    return max(cands, key=lambda p: p.stat().st_mtime)


def error_tail(output: str, lines: int = 40) -> str:
    """取日志尾部用于喂给 AI 修复。"""
    nonempty = [ln for ln in output.splitlines() if ln.strip()]
    return "\n".join(nonempty[-lines:])


# ------------------------------------------------------------------ 成片体检

def probe_video(mp4_path, min_duration: float = 3.0,
                log_cb=None) -> list[str]:
    """渲染后的"成片体检"：纯本地 ffmpeg 探测，返回人类可读的警告列表。

    说明：这里只能查出"物理层"的异常（黑屏、静止、时长、残缺）。
    "高亮停在错误格子上"这类语义级画面错误无法自动判定 —— 那需要视觉模型，
    目前 DeepSeek 平台不提供。体检只做低成本的兜底报警，不做审美判断。
    """
    warnings: list[str] = []

    def report(msg: str):
        warnings.append(msg)
        if log_cb:
            log_cb(msg)

    try:
        import imageio_ffmpeg
        exe = imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        report("未找到 ffmpeg，跳过成片体检")
        return warnings

    mp4_path = Path(mp4_path)
    if not mp4_path.exists() or mp4_path.stat().st_size == 0:
        report("成片文件不存在或为空")
        return warnings

    def run_ffprobe(args: list[str]) -> str:
        r = subprocess.run([exe, "-hide_banner", *args], capture_output=True,
                           text=True, encoding="utf-8", errors="ignore",
                           timeout=180, creationflags=_NO_WINDOW)
        return r.stderr

    # 1) 元信息：时长 / 分辨率
    try:
        info = run_ffprobe(["-i", str(mp4_path)])
        m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", info)
        if not m:
            report("无法读取视频元信息，文件可能损坏")
            return warnings
        duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
        if duration < min_duration:
            report(f"视频仅 {duration:.1f} 秒（短于 {min_duration:.0f}s），疑似渲染不完整")
        mres = re.search(r"Video:.*?,\s*(\d{2,5})x(\d{2,5})", info)
        if mres:
            w, h = int(mres.group(1)), int(mres.group(2))
            if w < 100 or h < 100:
                report(f"分辨率异常：{w}x{h}")
    except Exception as e:
        report(f"成片体检（元信息）未完成：{e}")
        return warnings

    # 2) 全黑画面段（阈值调到"真·全黑"：连白字都没有才算，manim 黑底白字是常态）
    try:
        err = run_ffprobe(["-i", str(mp4_path), "-vf",
                           "blackdetect=d=0.5:pix_th=0.02:pic_th=0.995",
                           "-an", "-f", "null", "-"])
        black_total = sum(float(x) for x in
                          re.findall(r"black_duration:([\d.]+)", err))
        if black_total > max(1.0, 0.25 * duration):
            report(f"检测到 {black_total:.1f}s 全黑画面"
                   f"（占 {black_total / duration:.0%}），可能内容缺失")
    except Exception as e:
        report(f"成片体检（黑屏检测）未完成：{e}")

    # 3) 静帧段（讲解时的刻意停顿属正常，只报"长到可疑"的）
    # 注意：freezedetect 在"静止持续到视频结尾"时只输出 freeze_start，不输出 freeze_duration，
    # 所以必须自己配对 start/end 计算时长。
    try:
        err = run_ffprobe(["-i", str(mp4_path), "-vf",
                           "freezedetect=n=-60dB:d=5",
                           "-an", "-f", "null", "-"])
        freeze_total = 0.0
        pending_start: float | None = None
        for line in err.splitlines():
            m = re.search(r"freeze_start:\s*([\d.]+)", line)
            if m:
                pending_start = float(m.group(1))
                continue
            m = re.search(r"freeze_end:\s*([\d.]+)", line)
            if m and pending_start is not None:
                freeze_total += float(m.group(1)) - pending_start
                pending_start = None
        if pending_start is not None:
            freeze_total += duration - pending_start   # 静止一直持续到片尾
        if freeze_total > 0:
            report(f"画面累计静止 {freeze_total:.1f}s（单段>5s），"
                   "若非刻意停顿请检查脚本里的 wait() 时长")
    except Exception as e:
        report(f"成片体检（静帧检测）未完成：{e}")

    return warnings
