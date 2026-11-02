"""MathViz 应用入口。启动方式（项目根目录）：

    .venv/Scripts/pythonw.exe -m app.main    # 无控制台窗口（run.bat 用这个）
    .venv/Scripts/python.exe  -m app.main    # 带控制台，排查问题用这个

pythonw.exe 不分配控制台，代价是 sys.stdout / sys.stderr 为 None、
崩溃时看不到任何提示。这里补齐三件事：把输出接到日志文件、
未捕获异常写 crash.log、并用系统弹窗把失败报出来。
"""
import datetime
import sys
import traceback

from PySide6.QtWidgets import QApplication

from app.core.config import DATA_DIR, ICON_FILE, ensure_dirs

# 日志必须写到用户目录：打包后程序目录（Program Files / _internal）可能只读，
# 写不进去的话崩溃就完全没有线索了。
LOG_DIR = DATA_DIR / "logs"
CONSOLE_LOG = LOG_DIR / "console.log"
CRASH_LOG = LOG_DIR / "crash.log"

# 应用图标：Windows 用 .ico（内含多尺寸）。
# 路径由 config 统一给出（基于项目根目录推导，从任何工作目录启动都找得到）。


def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _attach_log_file():
    """安静模式下没有控制台，把 stdout / stderr 接到 logs/console.log。

    不只是为了留痕：第三方库若直接 sys.stdout.write(...) 会因 None 而崩，
    print 的报错信息也会彻底蒸发，出问题只能盲猜。
    """
    if sys.stdout is not None and sys.stderr is not None:
        return
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    fp = open(CONSOLE_LOG, "a", encoding="utf-8", buffering=1)
    fp.write(f"\n===== MathViz 启动 {_stamp()} =====\n")
    sys.stdout = sys.stderr = fp


def _alert(title: str, text: str):
    """无控制台时，崩溃总得有个地方让人看见。"""
    try:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, title, 0x10)  # MB_ICONERROR
    except Exception:
        pass


_SW_SHOWNORMAL = 1
_SW_SHOW = 5
_SW_RESTORE = 9
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040
_HWND_TOP = 0


def _bring_to_front(window) -> str:
    """确保主窗口真的被人看见。

    用 pythonw / VBS 启动时，父进程（wscript）会把 STARTUPINFO 里的
    SW_HIDE 传给孩子 —— 结果是：进程好好地活着，内存也占着，但窗口
    既不显示也不进任务栏，看起来就像"程序没启动"。这里用 Win32 兜底：
    先判断是否最小化 / 不可见，再把它拉出来并置顶一瞬。
    """
    if sys.platform != "win32":
        return "非 Windows，跳过"
    try:
        import ctypes
        user32 = ctypes.windll.user32
        hwnd = int(window.winId())     # 访问 winId() 会强制创建原生窗口
        state = []
        if user32.IsIconic(hwnd):
            state.append("最小化")
            user32.ShowWindow(hwnd, _SW_RESTORE)
        if not user32.IsWindowVisible(hwnd):
            state.append("不可见")
            user32.ShowWindow(hwnd, _SW_SHOWNORMAL)
        user32.SetWindowPos(hwnd, _HWND_TOP, 0, 0, 0, 0,
                            _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW)
        user32.SetForegroundWindow(hwnd)
        visible = bool(user32.IsWindowVisible(hwnd))
        return (f"hwnd={hwnd} 启动态=[{'/'.join(state) or '正常'}] "
                f"处理后可见={visible}")
    except Exception as e:
        return f"兜底失败: {e}"


def _set_app_user_model_id():
    """让 Windows 任务栏显示我们自己的图标，而不是 python(w).exe 的。

    不做这一步的话，任务栏会把窗口归到"Python"那一组，
    即便标题栏图标已经换掉，任务栏上看到的仍是默认的 Python 图标。
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MathViz.App")
    except Exception:
        pass


def _set_app_icon(app) -> str:
    """设置整个应用的图标（标题栏 + 任务栏 + 所有对话框）。"""
    try:
        from PySide6.QtGui import QIcon
        if not ICON_FILE.exists():
            return f"未找到图标文件：{ICON_FILE}"
        icon = QIcon(str(ICON_FILE))
        if icon.isNull():
            return "Qt 无法解析该图标文件（可能不是有效的 ico）"
        sizes = icon.availableSizes()
        app.setWindowIcon(icon)
        dims = "/".join(f"{s.width()}×{s.height()}" for s in sizes) or "未知"
        return f"{ICON_FILE.name}（{len(sizes)} 种尺寸：{dims}）"
    except Exception as e:
        return f"设置图标失败：{e}"


def _excepthook(exc_type, exc, tb):
    detail = "".join(traceback.format_exception(exc_type, exc, tb))
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with open(CRASH_LOG, "a", encoding="utf-8") as f:
            f.write(f"\n===== {_stamp()} =====\n{detail}")
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc, tb)
    _alert("MathViz 崩溃", f"{exc_type.__name__}: {exc}\n\n详细堆栈已写入：\n{CRASH_LOG}")


def main():
    ensure_dirs()
    _attach_log_file()
    sys.excepthook = _excepthook
    _set_app_user_model_id()   # 必须在 QApplication 之前，任务栏图标才归属自己
    app = QApplication(sys.argv)
    app.setApplicationName("MathViz")
    print(f"[图标] {_set_app_icon(app)}")

    # 退出时收掉还在跑的 manim。父进程退出不会连带杀子进程 —— 不管它的话，
    # 用户关掉窗口后渲染仍在后台跑几分钟，占满 CPU 还锁着 media 目录。
    from app.core import renderer as _renderer

    def _kill_renderers():
        n = _renderer.terminate_active()
        if n:
            print(f"[退出] 已终止 {n} 个仍在运行的渲染进程")

    app.aboutToQuit.connect(_kill_renderers)

    # 作者用的「反馈台」：不需要主界面，直接开列表窗口。
    # 单独走一个入口而不是塞进主窗口菜单，是为了能从命令行/快捷方式直达。
    if "--feedback-inbox" in sys.argv:
        from PySide6.QtCore import QSettings
        from app.ui import theme
        mode = QSettings("MathViz", "MathViz").value("ui_theme", "light", type=str)
        app.setStyleSheet(theme.app_qss(theme.resolve(mode)))
        from app.ui.feedback_inbox import FeedbackInbox
        inbox = FeedbackInbox()
        inbox.show()
        app.processEvents()
        print(f"[反馈台] {_bring_to_front(inbox)}")
        sys.exit(app.exec())

    from app.ui.main_window import MainWindow
    window = MainWindow()
    window.show()
    app.processEvents()      # 让原生窗口先真正建出来，再谈可见性
    if not window.isVisible():
        window.setVisible(True)
    print(f"[窗口] {_bring_to_front(window)}｜屏幕几何 {window.frameGeometry()}")
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
