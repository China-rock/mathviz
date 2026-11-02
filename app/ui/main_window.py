"""主窗口：课件 → 知识点 → 对话确认 → 脚本 → 渲染 → 播放 的一条龙驾驶舱。"""
import contextlib
import html as html_mod
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from PySide6.QtCore import (QEvent, QSettings, Qt, QSize, QThread, QTimer,
                            QUrl, Signal)
from PySide6.QtGui import (QAction, QDesktopServices, QKeySequence, QPixmap,
                           QShortcut)
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox,
                               QComboBox, QDialog, QFileDialog, QFrame,
                               QGridLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPlainTextEdit,
                               QProgressBar, QPushButton, QScrollArea,
                               QSlider, QSpinBox, QSplitter, QTabWidget,
                               QTextBrowser, QTextEdit, QVBoxLayout, QWidget)

from app.core import (cache, config, diagnose, domains, feedback, llm, parser,
                      renderer, texenv, validator, versions)
from app.ui import handout, icons
from app.ui import theme
from app.ui.batch_dialog import BatchDialog
from app.ui.code_editor import CodeEditor, FindBar
from app.ui.first_run import ApiKeyDialog, maybe_notify_tex, tex_ready
from app.ui.feedback_dialog import FeedbackDialog
from app.ui.formula_dialog import FormulaDialog
from app.ui.settings_dialog import SettingsDialog
from app.ui.video_canvas import VideoCanvas


# ---------------------------------------------------------------- workers

def _emit_pacing(code: str, emit):
    """渲染前的节奏体检，把 AI 排出来的预计秒数翻译回人话。

    本项目不要求用户填"视频要做多少秒" —— 那是他最难把握的东西，
    节奏交给提示词里的「中等偏慢」口径去约束（45~80 秒）。
    这一层负责在**按下渲染之前**告诉他：AI 这次排出来大概是 20 秒还是 70 秒，
    并对"太赶"的写法点名 —— 免得白等一次渲染才发现片子一闪而过。
    """
    secs, hints = validator.pacing_report(code)
    if not secs:
        for h in hints:
            emit(f"[节奏体检] ⚠ {h}")
        return
    emit(f"[节奏体检] 预计成片约 {secs:.0f} 秒（中等偏慢的目标区间：45~80 秒）")
    for h in hints:
        emit(f"[节奏体检] ⚠ {h}")


class ExtractWorker(QThread):
    log = Signal(str)
    done = Signal(list)
    fail = Signal(str)

    def __init__(self, text, domain=domains.DEFAULT_DOMAIN):
        super().__init__()
        self.text = text
        self.domain = domain

    def run(self):
        try:
            self.log.emit("正在调用 DeepSeek 提取知识点……")
            points = llm.extract_points(self.text, self.domain)
            self.log.emit(f"提取到 {len(points)} 个知识点")
            self.done.emit(points)
        except Exception as e:
            self.fail.emit(str(e))


class ChatWorker(QThread):
    """对话式策划：根据课件（可为空）与聊天记录，产出/更新"呈现清单"。"""
    log = Signal(str)
    done = Signal(str)
    fail = Signal(str)

    def __init__(self, history, course_text, domain=domains.DEFAULT_DOMAIN):
        super().__init__()
        self.history = history
        self.course_text = course_text
        self.domain = domain

    def run(self):
        try:
            self.log.emit("正在与 DeepSeek 确认呈现内容……")
            reply = llm.plan_content(self.history, self.course_text, self.domain)
            self.done.emit(reply)
        except Exception as e:
            self.fail.emit(str(e))


class ReviseWorker(QThread):
    """代码修改模式：按用户的画面效果要求直接改现有脚本（不动呈现清单）。"""
    log = Signal(str)
    done = Signal(str)
    fail = Signal(str)

    def __init__(self, code, request, scene_name, domain=domains.DEFAULT_DOMAIN):
        super().__init__()
        self.code, self.request, self.scene_name = code, request, scene_name
        self.domain = domain

    def run(self):
        try:
            self.log.emit("正在按你的要求修改脚本……")
            code = llm.revise_script(self.code, self.request,
                                     self.scene_name, self.domain)
            ok, msg = validator.check(code, self.scene_name)
            if not ok:
                self.log.emit(f"静态检查未过（{msg}），请求 DeepSeek 自修复……")
                code = llm.fix_script(code, msg, self.scene_name, self.domain)
                ok, msg = validator.check(code, self.scene_name)
                if not ok:
                    self.fail.emit(f"修改后的脚本静态检查未通过：{msg}")
                    return
            for h in validator.layout_hints(code):
                self.log.emit(f"[布局体检] ⚠ {h}")
            _emit_pacing(code, self.log.emit)
            self.done.emit(code)
        except Exception as e:
            self.fail.emit(str(e))


class TopicWorker(QThread):
    """把用户的口语化需求提炼成一个简短知识点名（脚本与成片都用它命名）。"""
    log = Signal(str)
    done = Signal(str)
    fail = Signal(str)

    def __init__(self, text, domain=domains.DEFAULT_DOMAIN):
        super().__init__()
        self.text, self.domain = text, domain

    def run(self):
        try:
            self.log.emit("正在把你的描述提炼成知识点标题……")
            self.done.emit(llm.summarize_topic(self.text, self.domain))
        except Exception as e:
            self.fail.emit(str(e))


class GenerateWorker(QThread):
    log = Signal(str)
    done = Signal(str, str)   # code, scene_name
    fail = Signal(str)

    def __init__(self, title, description, level, context, scene_name,
                 domain=domains.DEFAULT_DOMAIN, plan: str = ""):
        super().__init__()
        self.title, self.description, self.level = title, description, level
        self.context, self.scene_name = context, scene_name
        self.domain = domain
        self.plan = plan

    def run(self):
        try:
            self.log.emit(f"正在为「{self.title}」生成 Manim 脚本……")
            code = llm.force_scene_name(
                llm.generate_script(self.title, self.description, self.level,
                                    self.context, self.scene_name, self.domain,
                                    plan=self.plan),
                self.scene_name)
            ok, msg = validator.check(code, self.scene_name)
            if not ok:
                self.log.emit(f"静态检查未过（{msg}），请求 DeepSeek 自修复……")
                code = llm.force_scene_name(
                    llm.fix_script(code, msg, self.scene_name, self.domain),
                    self.scene_name)
                ok, msg = validator.check(code, self.scene_name)
                if not ok:
                    self.fail.emit(f"生成脚本静态检查未通过：{msg}")
                    return
            self.log.emit("脚本生成完毕，静态检查通过")
            for h in validator.layout_hints(code):
                self.log.emit(f"[布局体检] ⚠ {h}")
            _emit_pacing(code, self.log.emit)
            self.done.emit(code, self.scene_name)
        except Exception as e:
            self.fail.emit(str(e))


class QuickCheckWorker(QThread):
    """版式快检：低帧率小分辨率跑一遍，回来只交一组定格图。

    它跟正式渲染走同一条 manim 管线，但产物不是成片（帧率只有 5，看不了），
    所以单独放在 renderer.QC_FRAME_DIR，不进 media/、也不参与缓存。
    """

    log = Signal(str)
    progress = Signal(int)
    done = Signal(bool, str, str)      # ok, 帧目录, 说明
    fail = Signal(str)

    def __init__(self, code, scene_name, layout="16:9", frames=6):
        super().__init__()
        self.code = code
        self.scene_name = scene_name
        self.layout = layout
        self.frames = frames

    def run(self):
        try:
            ok, dest, msg = renderer.render_quickcheck(
                self.code, self.scene_name, self.layout,
                frames=self.frames, log_cb=self.log.emit,
                progress_cb=self.progress.emit)
            self.done.emit(ok, str(dest) if dest else "", msg)
        except Exception as e:
            self.fail.emit(f"快检线程异常：{e}")


class ExportWorker(QThread):
    """导出 GIF / 关键帧 / 讲义 PDF。ffmpeg 转码要跑几秒到几十秒，必须放线程里。

    注意这里不碰 manim —— 抽帧和转码都直接读已经生成的 mp4，
    既快又保证结果和你看到的成片一致。
    """
    log = Signal(str)
    done = Signal(bool, str, str)   # ok, 目标路径, 消息
    fail = Signal(str)

    def __init__(self, kind: str, src: str, stem: str, **kw):
        super().__init__()
        self.kind = kind
        self.src = src
        self.stem = stem
        self.kw = kw

    def run(self):
        try:
            self.log.emit(f"[导出] 开始处理 {os.path.basename(self.src)}……")
            if self.kind == "gif":
                ok, dest, msg = renderer.export_gif(
                    self.src, archive_stem=self.stem, log_cb=self.log.emit,
                    **self.kw)
            elif self.kind == "handout":
                ok, dest, msg = handout.build_handout(
                    self.stem, self.kw.get("code", ""), self.src,
                    domain_label=self.kw.get("domain_label", ""),
                    log_cb=self.log.emit)
            else:
                ok, dest, msg = renderer.export_frames(
                    self.src, archive_stem=self.stem, log_cb=self.log.emit,
                    **self.kw)
            self.done.emit(ok, str(dest) if dest else "", msg)
        except Exception as e:
            self.fail.emit(f"导出线程异常：{e}")


class RenderWorker(QThread):
    log = Signal(str)
    done = Signal(bool, object, str)   # ok, mp4_path, message
    fail = Signal(str)                 # 未预期的内部异常
    progress = Signal(int)             # 0~100，由 manim 的逐动画进度条换算

    MAX_ATTEMPTS = 3

    def __init__(self, code, scene_name, quality, domain=domains.DEFAULT_DOMAIN,
                 archive_stem: str | None = None, layout: str = "16:9",
                 anim_range: tuple[int, int] | None = None):
        super().__init__()
        self.code, self.scene_name, self.quality = code, scene_name, quality
        self.domain = domain
        self.archive_stem = archive_stem
        self.layout = layout
        self.anim_range = anim_range

    def run(self):
        try:
            self._run()
        except Exception as e:
            self.fail.emit(f"渲染线程异常：{e}")

    def _run(self):
        code = self.code
        for attempt in range(1, self.MAX_ATTEMPTS + 1):
            ok, msg = validator.check(code, self.scene_name)
            if not ok:
                self.log.emit(f"[静态检查] {msg}")
                fixed = self._auto_fix(code, msg)
                if fixed is None:
                    break
                code = fixed
            self.log.emit(f"===== 渲染尝试 {attempt}/{self.MAX_ATTEMPTS} ({self.quality}) =====")
            ok, mp4, output = renderer.render(code, self.scene_name,
                                              self.quality, log_cb=self.log.emit,
                                              archive_stem=self.archive_stem,
                                              layout=self.layout,
                                              anim_range=self.anim_range,
                                              progress_cb=self.progress.emit)
            if ok:
                # 真实时长先落一行：与生成时的"[节奏体检] 预计成片约 N 秒"互为印证，
                # 用户不必自己盯表，也能看出 AI 这次节奏排得是快是慢。
                dur = renderer.video_duration(mp4)
                if dur:
                    self.log.emit(f"[成片] 实际时长 {dur:.1f} 秒")
                # 成片体检：黑屏 / 静帧 / 时长（纯本地，秒级）。语义级画面问题仍需人看。
                self.log.emit("[成片体检] 检查成片（黑屏/静帧/时长）……")
                issues = renderer.probe_video(mp4, log_cb=self.log.emit)
                if issues:
                    for it in issues:
                        self.log.emit(f"[成片体检] ⚠ {it}")
                else:
                    self.log.emit("[成片体检] 通过")
                self.done.emit(True, mp4, "渲染成功")
                return
            tail = renderer.error_tail(output)
            if attempt < self.MAX_ATTEMPTS:
                self.log.emit("渲染失败，尝试让 DeepSeek 修复脚本后重渲……")
                fixed = self._auto_fix(code, tail)
                if fixed is None:
                    break
                code = fixed
        self.done.emit(False, None, "渲染失败（含自动修复尝试），详见日志")

    def _auto_fix(self, code, error_text):
        if not config.get_api_key():
            self.log.emit("[自动修复] 未配置 API Key，跳过自动修复")
            return None
        try:
            fixed = llm.fix_script(code, error_text, self.scene_name, self.domain)
            self.log.emit("[自动修复] DeepSeek 已返回修复版")
            return fixed
        except Exception as e:
            self.log.emit(f"[自动修复失败] {e}")
            return None


class BatchWorker(QThread):
    """批量队列：逐个知识点 生成 → 检查 → 渲染，串行跑在后台线程里。

    为什么串行不并行：一支片子要独占一份 manim 子进程 + 一份 LaTeX 编译，
    并行只会让几支一起卡在同一个 CPU 上，还把日志搅成一锅粥；
    串行的观感是"一支接一支出片"，进度看得见，也随时能停。

    单个知识点失败绝不拖累后面的（各自的 try 包住），
    因为批量最怕的就是"第 3 个挂了，后面 9 个白排"。
    """
    log = Signal(str)
    progress = Signal(int, int, str)         # 已处理数, 总数, 当前标题
    item_done = Signal(str, str, str, str)   # title, code, mp4, 错误说明（成功时为空）
    done = Signal(int, int, bool)            # 成功数, 总数, 是否被取消
    fail = Signal(str)

    def __init__(self, items, quality, domain=domains.DEFAULT_DOMAIN,
                 context: str = "", layout: str = "16:9"):
        super().__init__()
        self.items = items
        self.quality = quality
        self.domain = domain
        self.context = context
        self.layout = layout
        self._cancel = False

    def cancel(self):
        """请求停止：正在渲的那一支渲完后才退出（不去强杀 manim 子进程）。"""
        self._cancel = True

    def run(self):
        try:
            self._run()
        except Exception as e:
            self.fail.emit(f"批量线程异常：{e}")

    def _run(self):
        total = len(self.items)
        ok_n = 0
        stamp = time.strftime("%m%d_%H%M%S")
        for i, kp in enumerate(self.items):
            if self._cancel:
                self.log.emit(f"[批量] 已按要求停止（完成 {i}/{total}）")
                self.done.emit(ok_n, total, True)
                return
            title = (kp.get("title") or f"知识点{i + 1}").strip()
            desc = kp.get("description", "")
            level = kp.get("level", "")
            self.progress.emit(i, total, title)
            self.log.emit(f"===== [批量 {i + 1}/{total}] {title} =====")
            scene_name = f"BATCH{stamp}_{i + 1}"
            try:
                self.log.emit("正在生成脚本……")
                code = llm.force_scene_name(
                    llm.generate_script(title, desc, level, self.context,
                                        scene_name, self.domain), scene_name)
                ok, msg = validator.check(code, scene_name)
                if not ok:
                    self.log.emit(f"静态检查未过（{msg}），请求 DeepSeek 自修复……")
                    code = llm.force_scene_name(
                        llm.fix_script(code, msg, scene_name, self.domain), scene_name)
                    ok, msg = validator.check(code, scene_name)
                if not ok:
                    self.log.emit(f"[批量] ✗ {title}：静态检查未通过（{msg}）")
                    self.item_done.emit(title, code, "", f"静态检查未通过：{msg}")
                    continue

                for h in validator.layout_hints(code):
                    self.log.emit(f"[布局体检] ⚠ {h}")
                secs, _ = validator.pacing_report(code)
                if secs:
                    self.log.emit(f"[节奏体检] 预计成片约 {secs:.0f} 秒")

                self.log.emit(f"开始渲染（{self.quality}）……")
                okr, mp4, _output = renderer.render(
                    code, scene_name, self.quality,
                    log_cb=self.log.emit, archive_stem=title,
                    layout=self.layout)
                if not okr:
                    self.log.emit(f"[批量] ✗ {title}：渲染失败（详见上面的日志）")
                    self.item_done.emit(title, code, "", "渲染失败（详见日志）")
                    continue
                renderer.probe_video(mp4, log_cb=self.log.emit)
                ok_n += 1
                self.item_done.emit(title, code, str(mp4), "")
            except Exception as e:
                self.log.emit(f"[批量] {title} 处理异常：{e}")
                self.item_done.emit(title, "", "", f"异常：{e}")
        self.done.emit(ok_n, total, False)


def _launch_file(path: str) -> tuple[bool, str]:
    """用系统默认程序打开文件：三重兜底，返回 (是否成功, 用了哪种方式 / 失败原因)。

    QDesktopServices.openUrl 在部分机器上会静默失败（路径含中文、空格，或关联
    程序注册异常时最明显），所以 Windows 上先走更贴近系统的 os.startfile，
    再退到 `cmd /c start`，最后才是 Qt 那层。
    """
    p = str(path)
    tried: list[str] = []
    if os.name == "nt":
        try:
            os.startfile(p)   # type: ignore[attr-defined]  # Windows 专有
            return True, "os.startfile"
        except Exception as e:
            tried.append(f"os.startfile 失败（{e}）")
        try:
            subprocess.Popen(
                ["cmd", "/c", "start", "", p],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            return True, "cmd start"
        except Exception as e:
            tried.append(f"cmd start 失败（{e}）")
    try:
        if QDesktopServices.openUrl(QUrl.fromLocalFile(p)):
            return True, "QDesktopServices"
        tried.append("QDesktopServices 返回 False")
    except Exception as e:
        tried.append(f"QDesktopServices 失败（{e}）")
    return False, "；".join(tried) or "没有可用的打开方式"


# ---------------------------------------------------------------- drop zone

class DropZone(QFrame):
    """课件投放区：虚线圆角框，点击打开文件对话框，或直接把文件拖进来。"""

    fileChosen = Signal(str)

    FILTER = "课件文件 (*.pdf *.pptx *.docx *.md *.txt *.tex)"

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("dropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

        v = QVBoxLayout(self)
        v.setContentsMargins(12, 20, 12, 20)
        v.setSpacing(8)

        self.lbl_plus = QLabel("＋")
        self.lbl_plus.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_plus.setStyleSheet(
            'font-family: "Microsoft YaHei"; font-size:38px;'
            " color:#b0b4bc; background:transparent;")
        self.lbl_hint = QLabel("拖拽文件到此处，或点击选择")
        self.lbl_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_hint.setStyleSheet(
            'font-family: "Microsoft YaHei"; font-size:13px;'
            " color:#8a9099; background:transparent;")
        # 明确写出能力边界：本程序只吃"文本层"，扫描件/图片里的字读不到
        self.lbl_fmt = QLabel(
            "支持 pdf / pptx / docx / md / txt / tex\n"
            "仅支持文字形式的文件，扫描件 / 图片型 PDF 无法识别")
        self.lbl_fmt.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.lbl_fmt.setWordWrap(True)
        self.lbl_fmt.setStyleSheet(
            'font-family: "Microsoft YaHei"; font-size:12px;'
            " color:#a08b6a; background:transparent;")

        v.addWidget(self.lbl_plus)
        v.addWidget(self.lbl_hint)
        v.addWidget(self.lbl_fmt)
        self._palette = None      # 由主窗口在主题切换时注入（见 set_palette）
        self._hot = False
        self._apply_style(False)

    def set_palette(self, p: dict):
        """主题切换：记住配色并重画一遍（含三个标签的文字色）。"""
        self._palette = p
        self.lbl_plus.setStyleSheet(
            'font-family: "Microsoft YaHei"; font-size:38px;'
            f" color:{p['border']}; background:transparent;")
        self.lbl_hint.setStyleSheet(
            'font-family: "Microsoft YaHei"; font-size:13px;'
            f" color:{p['sub']}; background:transparent;")
        self.lbl_fmt.setStyleSheet(
            'font-family: "Microsoft YaHei"; font-size:12px;'
            f" color:{p['sub']}; background:transparent;")
        self._apply_style(self._hot)

    def _apply_style(self, drag_over: bool):
        self._hot = drag_over
        p = self._palette
        if p is None:
            from app.ui import theme as _theme
            p = _theme.palette("light")
        self.setStyleSheet(theme.drop_qss(p, drag_over))

    # ---- 拖拽

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
            self._apply_style(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        self._apply_style(False)

    def dropEvent(self, event):
        self._apply_style(False)
        for url in event.mimeData().urls():
            if url.isLocalFile():
                self.fileChosen.emit(url.toLocalFile())
                return

    # ---- 点击 = 资源管理器

    def open_dialog(self):
        """弹资源管理器选课件（点击与「文件→打开课件」菜单共用）。"""
        path, _ = QFileDialog.getOpenFileName(self, "选择课件", "", self.FILTER)
        if path:
            self.fileChosen.emit(path)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.open_dialog()


# ---------------------------------------------------------------- window

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MathViz — 课件转数学动画（DeepSeek × Manim）")
        self.resize(1440, 860)

        self.course_text = ""
        self.knowledge_points: list[dict] = []
        self.current_scene_name = ""
        self._current_point_title = ""  # 当前知识点标题，用于成片命名（见下方 property）
        self._history_entries: list = []   # 历史成果列表对应的缓存条目
        self._worker = None
        self._kp_counter = 0
        self.chat_history: list[dict] = []   # 喂给 LLM 的对话记录（user/assistant）
        self.chat_plan = ""                  # 最近一次确认的"呈现清单"，生成脚本的依据
        self.chat_bubbles: list[tuple] = []  # 当前对话已渲染的气泡（切会话时重放用）
        self.chat_sessions: list[dict] = []  # 归档的上一场/上几场对话（切换知识点时自动收起）
        self.chat_topic = ""                 # 当前对话属于哪个知识点（空 = 自由对话）

        self._build_ui()
        # 批量队列的进度与"停止"放状态栏：跑起来才出现、结束即隐藏，
        # 不占工作区的常驻位置（那排按钮已经够挤了）。
        self.batch_bar = QProgressBar()
        self.batch_bar.setMaximumWidth(200)
        self.batch_bar.setTextVisible(True)
        self.batch_bar.hide()
        self.btn_batch_stop = QPushButton("■ 停止")
        self.btn_batch_stop.setToolTip("当前这一支渲完后停止；已完成的成片不受影响")
        self.btn_batch_stop.clicked.connect(self._stop_batch)
        self.btn_batch_stop.hide()
        _sb = self.statusBar()
        # 渲染/快检的进度条：manim 的进度是"逐动画"打的，这里换算成总体百分比
        self.render_bar = QProgressBar()
        self.render_bar.setMaximumWidth(180)
        self.render_bar.setTextVisible(True)
        self.render_bar.setFormat("渲染 %p%")
        self.render_bar.hide()
        _sb.addPermanentWidget(self.render_bar)
        _sb.addPermanentWidget(self.batch_bar)
        _sb.addPermanentWidget(self.btn_batch_stop)
        self._batch_worker = None
        self._batch_last_mp4 = ""
        self._batch_quality = "low"
        self._build_media()
        self._build_media_shortcuts()   # 空格/方向键/逐帧/F11（要在 _build_media 之后）
        self._build_editor_shortcuts()  # Ctrl+F/H/L+/ 作用在脚本编辑器上
        self._apply_theme()             # 主题与字号要在对话气泡画出来之前定好
        self._watch_system_theme()      # 选了跟随系统时，系统改配色要跟着改
        self._restore_layout_mode()   # 恢复上次的布局（要在 _build_media 后：需要 current_video）
        self._reset_chat()          # 开场白：告诉用户两条入口（课件 / 直接输入）
        self._refresh_key_status()
        self._apply_quality_ui()    # 按钮/菜单文案跟着画质档位（可能从设置恢复成了 720p）
        self._refresh_buttons()     # 菜单里的运行动作与按钮初始状态对齐
        self._refresh_history()     # 把以前做过的知识点摆出来（缓存是跨会话的）
        self._refresh_chat_combo()  # 对话分页下拉框（初始只有"当前"一项）
        self._refresh_versions()    # 版本下拉框（初始只有"当前编辑器"）
        # 首启检查要等窗口画出来之后再弹（构造期弹窗会卡在半初始化的界面上）
        QTimer.singleShot(0, self._first_run)

    def _render_in_progress(self) -> str:
        """正在渲染就返回一句进度描述，否则返回空串。

        三种情况都算：单支渲染线程在跑、批量队列在跑、以及有 manim 子进程活着
        （快检之类不经过 RenderWorker 的渲染）。只判线程会漏掉"线程已建但
        manim 还没起来"的瞬间，只判进程会漏掉两支之间的空档。
        """
        w = getattr(self, "_worker", None)
        if isinstance(w, RenderWorker) and w.isRunning():
            pct = self.render_bar.value() if hasattr(self, "render_bar") else 0
            return f"正在渲染「{self.current_point_title or '当前动画'}」，进度 {pct}%"
        bw = getattr(self, "_batch_worker", None)
        if isinstance(bw, BatchWorker) and bw.isRunning():
            bar = getattr(self, "batch_bar", None)
            now = bar.value() if bar is not None else 0
            total = bar.maximum() if bar is not None else 0
            return f"正在批量渲染，第 {now} / {total} 个"
        try:
            if renderer.active_count() > 0:
                return "Manim 正在执行渲染"
        except Exception:
            pass
        return ""

    def _confirm_abort_render(self, detail: str) -> bool:
        """问一句"真的要在渲染时关掉吗"。返回 True 表示用户选择继续关闭。

        默认按钮是「继续渲染」——手滑按回车不应该丢掉一次几分钟的渲染。
        自动化测试（offscreen）下不弹模态框，否则测试会卡死；测试要验证这个
        框本身时设 MATHVIZ_TEST_DIALOGS=1 绕过（只影响这一个框）。
        """
        if (os.environ.get("QT_QPA_PLATFORM") == "offscreen"
                and not os.environ.get("MATHVIZ_TEST_DIALOGS")):
            return True
        box = QMessageBox(self)
        box.setWindowTitle("正在渲染")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"{detail}。")
        box.setInformativeText(
            "现在关闭会中断这次渲染，已经渲好的部分不会保留"
            "（批量任务里已完成的那几支仍然保存在历史中）。\n\n"
            "想保留这次结果，请点「继续渲染」，等它跑完再关。")
        btn_wait = box.addButton("继续渲染", QMessageBox.ButtonRole.RejectRole)
        btn_quit = box.addButton("仍然关闭", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(btn_wait)
        box.setEscapeButton(btn_wait)      # 按 Esc 也默认"别关"
        box.exec()
        return box.clickedButton() is btn_quit

    def closeEvent(self, event):
        """关窗口时先问一嘴，再把还在跑的 manim 收掉。

        QThread 里启动的渲染进程不会随窗口消失：父进程退出不连带杀子进程，
        它会继续跑到结束（可能几分钟），期间占着 media 目录，下次渲染就报
        "文件被占用"。所以关窗前必须杀进程。

        但"直接杀掉"对用户是无声的损失 —— 一次渲染可能要十几分钟，关窗
        往往只是手滑。因此正在渲染时先弹确认框，默认按钮是"继续渲染"。
        """
        detail = self._render_in_progress()
        if detail and not self._confirm_abort_render(detail):
            event.ignore()
            self._log("[退出] 已取消关闭：渲染还在进行")
            return
        # 先叫停批量队列，免得它被杀掉一支后又接着起下一支
        bw = getattr(self, "_batch_worker", None)
        if isinstance(bw, BatchWorker):
            with contextlib.suppress(Exception):
                bw.cancel()
        try:
            n = renderer.terminate_active()
            if n:
                self._log(f"[退出] 已终止 {n} 个仍在运行的渲染进程")
        except Exception:
            pass
        # 进程刚被杀，渲染线程还要把返回值处理完；等一小会儿再退，
        # 否则 Qt 会报 "QThread: Destroyed while thread is still running"。
        w = getattr(self, "_worker", None)
        if isinstance(w, (RenderWorker, BatchWorker)) and w.isRunning():
            w.wait(4000)
        super().closeEvent(event)

    def _first_run(self):
        """打包分发后第一次打开时，把"必须用户自己给的东西"补齐。

        两件事：① DeepSeek Key（只能用户自己申请）② LaTeX（打不进安装包）。
        开发环境这两样都齐，所以平时看不到任何弹窗。
        """
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            return      # 自动化测试环境：模态框会让测试卡死，直接跳过
        if not config.get_api_key():
            dlg = ApiKeyDialog(self, first_run=True)
            dlg.exec()          # 首次不能跳过：没有 Key 后面每一步都会失败
            self._refresh_key_status()
        maybe_notify_tex(self)

    # ---------- 当前标题（脚本与成片都用它命名）

    @property
    def current_point_title(self) -> str:
        return self._current_point_title

    @current_point_title.setter
    def current_point_title(self, value):
        """赋值即同步右上角标题标签 —— 避免改名后界面还显示旧的。"""
        self._current_point_title = (value or "").strip()
        lbl = getattr(self, "lbl_title", None)   # _build_ui 之前还没有这个标签
        if lbl is not None:
            lbl.setText(f"📌 {self._current_point_title}"
                        if self._current_point_title else "")
            lbl.setToolTip("脚本与成片的标题"
                           + ("（直接对话时由 AI 从你的描述中提炼）"
                              if self._current_point_title else ""))

    # ---------- UI 组装

    def _build_ui(self):
        root_splitter = QSplitter()
        self.setCentralWidget(root_splitter)

        # 左：文件输入 + 目标知识点
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(8, 8, 4, 8)

        self.drop_zone = DropZone()
        self.drop_zone.fileChosen.connect(self.on_file_chosen)
        self.lbl_file = QLabel("尚未打开课件")
        self.lbl_file.setWordWrap(True)

        # 学科选择：下拉内容由 app/core/domains.py 里的领域包决定，
        # 新增学科只需在那里注册一个 DomainPack，这里不用改。
        domain_row = QHBoxLayout()
        domain_row.addWidget(QLabel("学科："))
        self.combo_domain = QComboBox()
        for pack in domains.list_packs():
            self.combo_domain.addItem(pack.label, pack.key)
        self.combo_domain.setToolTip(
            "内置 5 个学科：数学 / 物理 / 线性代数 / 概率统计 / 数据结构。\n"
            "切换学科会改变「提取知识点」与「生成脚本」用的提示词（按学科给不同的\n"
            "可视化技法和示例），缓存与历史成果也按学科分开存放。\n"
            "新增学科：在 app/core/domains.py 注册一个领域包即可自动出现在这里。")
        domain_row.addWidget(self.combo_domain, 1)
        lv.addLayout(domain_row)

        self.btn_extract = QPushButton("🔍 提取知识点")
        self.btn_extract.setEnabled(False)
        self.btn_extract.clicked.connect(self.on_extract)
        self.point_list = QListWidget()
        self.point_list.setMouseTracking(True)   # 不按键也能收到 itemEntered
        self.point_list.itemDoubleClicked.connect(self.on_point_activated)
        self.point_list.setStyleSheet(theme.list_qss(theme.LIGHT))
        self._build_kp_send_button()

        lv.addWidget(self.drop_zone)
        lv.addWidget(self.lbl_file)
        lv.addWidget(self.btn_extract)
        kp_head = QHBoxLayout()
        kp_head.addWidget(QLabel("知识点（双击或点 ➜ 送入对话确认）："))
        kp_head.addStretch(1)
        self.btn_batch = QPushButton("🗂 批量")
        self.btn_batch.setEnabled(False)
        self.btn_batch.setToolTip(
            "把多个知识点一次排队：逐个生成脚本并渲染，出片自动归档。\n"
            "先低质量审片、满意的再高清重渲，是成本最低的做法。")
        self.btn_batch.clicked.connect(self.on_batch)
        kp_head.addWidget(self.btn_batch)
        lv.addLayout(kp_head)

        # 知识点列表与历史成果之间用可拖动分割条：两者高度都能自己调
        left_split = QSplitter()
        left_split.setOrientation(Qt.Orientation.Vertical)
        left_split.setChildrenCollapsible(False)

        point_box = QWidget()
        pv = QVBoxLayout(point_box)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(self.point_list)   # 已在上面建好（含双击/悬停按钮等连接）

        self.history_list = QListWidget()
        self.history_list.setMouseTracking(True)
        self.history_list.setStyleSheet(theme.list_qss(theme.LIGHT))
        self.history_list.itemDoubleClicked.connect(self._on_history_activated)
        self.history_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.history_list.customContextMenuRequested.connect(self._history_menu)
        hist_box = QWidget()
        hv = QVBoxLayout(hist_box)
        hv.setContentsMargins(0, 0, 0, 0)
        hv.addLayout(self._build_history_row())
        hv.addWidget(self.history_list)

        left_split.addWidget(point_box)
        left_split.addWidget(hist_box)
        left_split.setSizes([420, 200])   # 历史框默认矮一点，拖一下就能变高
        lv.addWidget(left_split, 1)

        self.lbl_key = QLabel()
        lv.addWidget(self.lbl_key)

        # 中：内容自定义与工作确认（对话窗口，无课件也能直接用）
        middle = self._build_chat_panel()

        # 右上：脚本预览 + 渲染操作
        editor_panel = QWidget()
        ev = QVBoxLayout(editor_panel)
        ev.setContentsMargins(4, 8, 8, 4)

        # 版本快照工具条：AI 每次改脚本都留一份，改坏了能退回去
        ver_bar = QHBoxLayout()
        ver_bar.setSpacing(4)
        lbl_ver = QLabel("版本：")
        ver_bar.addWidget(lbl_ver)
        self.cmb_version = QComboBox()
        self.cmb_version.setMinimumWidth(170)
        self.cmb_version.setToolTip(
            "脚本的历史快照（生成 / 代码修改 / 渲染成功都会自动留一版）。\n"
            "选中某版后点「退回」即可把编辑器还原到那时；「差异」看两版改了什么。")
        self.cmb_version.currentIndexChanged.connect(self._on_version_selected)
        ver_bar.addWidget(self.cmb_version)
        self.btn_ver_revert = QPushButton("↩ 退回")
        self.btn_ver_revert.setEnabled(False)
        self.btn_ver_revert.setToolTip("把编辑器内容还原到选中的那一版（当前内容会自动存为新版本）")
        self.btn_ver_revert.clicked.connect(self._revert_version)
        self.btn_ver_diff = QPushButton("🔍 差异")
        self.btn_ver_diff.setEnabled(False)
        self.btn_ver_diff.setToolTip("对比选中版本与编辑器当前内容的差别")
        self.btn_ver_diff.clicked.connect(self._diff_version)
        self.btn_ver_save = QPushButton("💾 存为版本")
        self.btn_ver_save.setEnabled(False)
        self.btn_ver_save.setToolTip("手动把当前编辑器内容存成一版（比如改完觉得满意，先打个锚点）")
        self.btn_ver_save.clicked.connect(self._save_version)
        for b in (self.btn_ver_revert, self.btn_ver_diff, self.btn_ver_save):
            ver_bar.addWidget(b)
        ver_bar.addStretch(1)
        ev.addLayout(ver_bar)

        top_bar = QHBoxLayout()
        # 渲染只有一个入口：按钮文字跟着画质下拉走，选 480p 就是预览、
        # 选 1080p 就是高清 —— 不再摆两个按钮让人纠结点哪个。
        self.btn_render = QPushButton("🎬 渲染（480p）")
        self.btn_render.setEnabled(False)
        self.btn_render.clicked.connect(lambda: self.on_render(self._current_quality()))
        top_bar.addWidget(self.btn_render)

        # 画质三档：480p 快、720p 够用、1080p 出片。帧率跟着档位走（15/30/60）。
        self.combo_quality = QComboBox()
        for key in ("low", "medium", "high"):
            self.combo_quality.addItem(
                f"{renderer.QUALITY_LABELS[key]}（{renderer.quality_fps(key)}fps）", key)
        self.combo_quality.setToolTip(
            "渲染画质（同时决定帧率）：\n"
            "· 480p/15fps —— 最快，用来审片、看版式对不对\n"
            "· 720p/30fps —— 折中，交作业、插课件都够\n"
            "· 1080p/60fps —— 出片，成片文件名会带 [HD] 前缀\n"
            "选择会记住；横屏走 manim 预设，竖屏/方形按短边换算。")
        self.combo_quality.currentIndexChanged.connect(self._on_quality_changed)
        _qi = self.combo_quality.findData(
            QSettings("MathViz", "MathViz").value("render_quality", "low"))
        if _qi >= 0:
            self.combo_quality.setCurrentIndex(_qi)
        top_bar.addWidget(self.combo_quality)

        self.combo_layout = QComboBox()
        for label, key in (("横屏 16:9", "16:9"),
                           ("竖屏 9:16", "9:16"),
                           ("方形 1:1", "1:1")):
            self.combo_layout.addItem(label, key)
        self.combo_layout.setToolTip(
            "渲染画幅：横屏适合投屏和作业提交，竖屏适合手机/短视频，方形居中。\n"
            "竖屏/方形成片的文件名会带 [竖]/[方] 前缀，和横屏版区分。\n"
            "选择会记住，下次打开还是它。")
        self.combo_layout.currentIndexChanged.connect(self._save_layout_choice)
        st = QSettings("MathViz", "MathViz")
        _idx = self.combo_layout.findData(st.value("render_layout", "16:9"))
        if _idx >= 0:
            self.combo_layout.setCurrentIndex(_idx)
        top_bar.addWidget(self.combo_layout)
        # 预计时长紧跟渲染按钮：按下渲染之前就该知道 AI 这次排了多久，
        # 而不是等成片出来才发现一闪而过。
        self.lbl_pacing = QLabel("预计时长：—")
        self.lbl_pacing.setToolTip("还没有可估算的脚本")
        top_bar.addWidget(self.lbl_pacing)
        top_bar.addStretch(1)
        self.lbl_title = QLabel("")
        top_bar.addWidget(self.lbl_title)
        self.lbl_scene = QLabel("")
        top_bar.addWidget(self.lbl_scene)
        ev.addLayout(top_bar)

        # 第二行：省时间的两个开关（版式快检 / 只渲某一段）。
        # 它们不是每次都要动，但挤进上一行会把播放和画质控件压扁，所以另起一行。
        run_bar = QHBoxLayout()
        run_bar.setSpacing(6)
        self.btn_qc = QPushButton("🔎 版式快检")
        self.btn_qc.setToolTip(
            "先花几秒渲一组定格图（低帧率 + 小分辨率），看看文字有没有压在一起、\n"
            "有没有出画。版式没问题再正式渲染 —— 省的是整支片子的等待。\n"
            "快检片子本身帧率只有 5，看不了，只出定格图。")
        self.btn_qc.clicked.connect(self.on_quickcheck)
        run_bar.addWidget(self.btn_qc)

        self.chk_range = QCheckBox("✂ 只渲第")
        self.chk_range.setToolTip(
            "只渲染脚本里的某几段（一段 = 一个 self.play / self.wait）。\n"
            "改了第 3 步就只重渲第 3 步，前面的步骤会瞬间到位、不占时长。\n"
            "注意：脚本里的 for 循环每转一圈算一段，实际段数会比代码里看到的多。")
        self.chk_range.toggled.connect(self._apply_range_enabled)
        run_bar.addWidget(self.chk_range)
        self.spin_from = QSpinBox()
        self.spin_to = QSpinBox()
        for sp in (self.spin_from, self.spin_to):
            sp.setRange(1, 1)
            sp.setAlignment(Qt.AlignmentFlag.AlignCenter)
            sp.setFixedWidth(58)
        run_bar.addWidget(self.spin_from)
        run_bar.addWidget(QLabel("~"))
        run_bar.addWidget(self.spin_to)
        run_bar.addWidget(QLabel("段"))
        self.lbl_plays = QLabel("（共 — 段）")
        self.lbl_plays.setToolTip("按脚本里 self.play / self.wait 的调用个数统计（循环按 1 次算）")
        run_bar.addWidget(self.lbl_plays)
        run_bar.addStretch(1)
        ev.addLayout(run_bar)
        self._apply_range_enabled()

        # 查找/替换条：平时收起，Ctrl+F 才出现，不占编辑器高度
        self.find_bar = FindBar(None)      # editor 建好后立刻绑定（见下）
        ev.addWidget(self.find_bar)

        self.editor = CodeEditor()
        self.find_bar.editor = self.editor
        ev.addWidget(self.editor, 1)

        # 语法错误实时提示：不是"报错拦着不让渲"，而是敲错的时候当场标出来。
        # 用独立定时器（600ms）而不是跟节奏体检共用一个：两者都要解析 AST，
        # 合在一起会让每次按键都付两份代价。
        self.lbl_syntax = QLabel("")
        self.lbl_syntax.setWordWrap(True)
        self.lbl_syntax.hide()
        ev.addWidget(self.lbl_syntax)
        self._syntax_timer = QTimer(self)
        self._syntax_timer.setSingleShot(True)
        self._syntax_timer.setInterval(600)
        self._syntax_timer.timeout.connect(self._refresh_syntax)
        self.editor.textChanged.connect(self._syntax_timer.start)

        # 手改脚本同样会改变节奏，跟着刷新；节流 400ms 免得每敲一个字符就重新解析一遍 AST
        self._pacing_timer = QTimer(self)
        self._pacing_timer.setSingleShot(True)
        self._pacing_timer.setInterval(400)
        self._pacing_timer.timeout.connect(self._refresh_pacing)
        self.editor.textChanged.connect(self._pacing_timer.start)
        self._refresh_pacing()
        self._refresh_syntax()

        # 右下：预览 / 日志
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_preview_page(), "预览")
        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setMaximumBlockCount(2000)
        self.tabs.addTab(self.log_view, "运行日志")

        right_splitter = QSplitter()
        right_splitter.setOrientation(Qt.Orientation.Vertical)
        right_splitter.addWidget(editor_panel)
        right_splitter.addWidget(self.tabs)
        right_splitter.setSizes([520, 340])

        root_splitter.addWidget(left)
        root_splitter.addWidget(middle)
        root_splitter.addWidget(right_splitter)
        root_splitter.setSizes([300, 380, 760])

        # 播放器模式要在这些面板上做显隐切换，留好引用
        self._left_panel = left
        self._middle_panel = middle
        self._editor_panel = editor_panel
        self.root_splitter = root_splitter
        self.right_splitter = right_splitter

        # 顶部菜单栏（文件 / 编辑 / 查看 / 运行 / 选项 / 帮助）
        self._build_menus()

    def _build_history_row(self) -> QHBoxLayout:
        """历史成果区的标题行（带一个刷新按钮）。"""
        row = QHBoxLayout()
        row.addWidget(QLabel("历史成果（双击载入）："))
        row.addStretch(1)
        btn = QPushButton("🔄")
        btn.setFixedWidth(32)
        btn.setToolTip("刷新历史列表（缓存是跨会话的：关掉程序再打开，这些成果仍在）")
        btn.clicked.connect(self._refresh_history)
        row.addWidget(btn)
        return row

    # ---------- 菜单栏（VSCode 式：文件 / 编辑 / 查看 / 运行 / 选项 / 帮助）

    def _build_menus(self):
        bar = self.menuBar()

        # ---- 文件
        m_file = bar.addMenu("文件(&F)")
        act_open = QAction("打开课件…", self)
        act_open.setShortcut("Ctrl+O")
        act_open.triggered.connect(self.drop_zone.open_dialog)
        m_file.addAction(act_open)
        m_file.addSeparator()
        act_media = QAction("打开成片文件夹", self)
        act_media.setToolTip("已渲染并归档的视频都在这里（media/）")
        act_media.triggered.connect(lambda: self._open_dir(config.OUTPUT_MEDIA_DIR))
        m_file.addAction(act_media)
        act_workdir = QAction("打开渲染工作目录", self)
        act_workdir.triggered.connect(lambda: self._open_dir(config.RENDER_WORK_DIR))
        m_file.addAction(act_workdir)
        m_file.addSeparator()
        self.act_export_gif = QAction("导出当前成片为 GIF…", self)
        self.act_export_gif.setShortcut("Ctrl+Shift+G")
        self.act_export_gif.triggered.connect(self.on_export_gif)
        self.act_export_gif.setEnabled(False)
        m_file.addAction(self.act_export_gif)
        self.act_export_frames = QAction("导出关键帧 PNG…", self)
        self.act_export_frames.setShortcut("Ctrl+Shift+P")
        self.act_export_frames.triggered.connect(self.on_export_frames)
        self.act_export_frames.setEnabled(False)
        m_file.addAction(self.act_export_frames)
        self.act_export_handout = QAction("导出讲义 PDF…", self)
        self.act_export_handout.setShortcut("Ctrl+Shift+H")
        self.act_export_handout.triggered.connect(self.on_export_handout)
        self.act_export_handout.setEnabled(False)
        m_file.addAction(self.act_export_handout)
        m_file.addSeparator()
        act_quit = QAction("退出", self)
        act_quit.setShortcut("Ctrl+Q")
        act_quit.triggered.connect(self.close)
        m_file.addAction(act_quit)

        # ---- 编辑（作用于当前获得焦点的文本框：脚本编辑器 / 对话输入 / 日志）
        m_edit = bar.addMenu("编辑(&E)")
        self._edit_menu_actions(m_edit)
        m_edit.addSeparator()
        act_find = QAction("查找…", self)
        act_find.setShortcut("Ctrl+F")
        act_find.setToolTip("在脚本里查找（查找条贴在编辑器上方，脚本仍可见可改）")
        act_find.triggered.connect(lambda: self._show_find_bar(False))
        m_edit.addAction(act_find)
        act_replace = QAction("替换…", self)
        act_replace.setShortcut("Ctrl+H")
        act_replace.triggered.connect(lambda: self._show_find_bar(True))
        m_edit.addAction(act_replace)
        act_goto = QAction("跳转到行…", self)
        act_goto.setShortcut("Ctrl+L")
        act_goto.triggered.connect(self._goto_line)
        m_edit.addAction(act_goto)
        act_comment = QAction("切换注释", self)
        act_comment.setShortcut("Ctrl+/")
        act_comment.setToolTip("把选中的每一行加上 / 去掉 # 注释")
        act_comment.triggered.connect(self._toggle_comment)
        m_edit.addAction(act_comment)
        m_edit.addSeparator()
        act_copy_code = QAction("复制脚本全文", self)
        act_copy_code.setShortcut("Ctrl+Shift+C")
        act_copy_code.triggered.connect(self._copy_script)
        m_edit.addAction(act_copy_code)

        # ---- 查看
        m_view = bar.addMenu("查看(&V)")
        act_tab_prev = QAction("预览页", self)
        act_tab_prev.setShortcut("Ctrl+1")
        act_tab_prev.triggered.connect(lambda: self.tabs.setCurrentIndex(0))
        m_view.addAction(act_tab_prev)
        act_tab_log = QAction("运行日志页", self)
        act_tab_log.setShortcut("Ctrl+2")
        act_tab_log.triggered.connect(lambda: self.tabs.setCurrentIndex(1))
        m_view.addAction(act_tab_log)
        m_view.addSeparator()
        act_zoom_in = QAction("编辑器字体放大", self)
        act_zoom_in.setShortcut("Ctrl+=")
        act_zoom_in.triggered.connect(lambda: self._zoom_editor(+1))
        m_view.addAction(act_zoom_in)
        act_zoom_out = QAction("编辑器字体缩小", self)
        act_zoom_out.setShortcut("Ctrl+-")
        act_zoom_out.triggered.connect(lambda: self._zoom_editor(-1))
        m_view.addAction(act_zoom_out)
        act_zoom_reset = QAction("编辑器字体重置", self)
        act_zoom_reset.setShortcut("Ctrl+0")
        act_zoom_reset.triggered.connect(lambda: self._zoom_editor(0))
        m_view.addAction(act_zoom_reset)
        m_view.addSeparator()
        # 播放器模式：朋友建议的"大屏视频 + 知识点目录"形态，可随时切回
        self.act_player_mode = QAction("▶ 播放器模式（大屏看片）", self)
        self.act_player_mode.setCheckable(True)
        self.act_player_mode.toggled.connect(self._toggle_player_mode)
        # 注意：这里【不】读 QSettings 恢复勾选 —— 菜单在 _build_ui 里构建，
        # 而 current_video 要等 _build_media 才出生；启动恢复挪到 __init__
        # 的 _build_media 之后统一做（见 _restore_layout_mode）。
        m_view.addAction(self.act_player_mode)

        # ---- 运行（可用状态与对应按钮同步）
        m_run = bar.addMenu("运行(&R)")
        self.act_extract = QAction("🔍 提取知识点", self)
        self.act_extract.setShortcut("Ctrl+E")
        self.act_extract.triggered.connect(self.on_extract)
        m_run.addAction(self.act_extract)
        self.act_generate = QAction("✅ 确认，生成脚本", self)
        self.act_generate.setShortcut("Ctrl+G")
        self.act_generate.triggered.connect(self.on_generate)
        m_run.addAction(self.act_generate)
        m_run.addSeparator()
        self.act_quickcheck = QAction("🔎 版式快检（先看定格图）", self)
        self.act_quickcheck.setShortcut("Ctrl+Shift+Q")
        self.act_quickcheck.setToolTip(
            "低帧率小分辨率渲一遍，抽几张定格图看版式，比整支渲完再发现重叠省时间")
        self.act_quickcheck.triggered.connect(self.on_quickcheck)
        m_run.addAction(self.act_quickcheck)
        self.act_render = QAction("🎬 渲染（480p）", self)
        self.act_render.setShortcut("Ctrl+R")
        self.act_render.triggered.connect(
            lambda: self.on_render(self._current_quality()))
        m_run.addAction(self.act_render)
        # Ctrl+Shift+R 保留为"临时高清"：不改画质选择，就这一次按 1080p 渲
        self.act_render_hd_once = QAction("🎥 就这一次按 1080p 渲（不改画质选择）", self)
        self.act_render_hd_once.setShortcut("Ctrl+Shift+R")
        self.act_render_hd_once.setToolTip(
            "临时用 1080p/60fps 渲这一次，画质下拉保持原样。\n"
            "想固定出高清，直接把画质下拉选到 1080p 再 Ctrl+R。")
        self.act_render_hd_once.triggered.connect(lambda: self.on_render("high"))
        m_run.addAction(self.act_render_hd_once)

        # ---- 选项（点击菜单直接弹设置窗口；原先散在「工具」菜单里的开关
        #      全部收进弹窗，一页看全、改完即生效）
        act_options = QAction("选项(&O)…", self)
        act_options.triggered.connect(self._open_settings)
        bar.addAction(act_options)
        # 缓存开关的真身：不再出现在菜单里（挪进了「选项」弹窗），
        # 但保留为可勾选动作，作为缓存状态唯一真相源 ——
        # _toggle_cache 会同步它，测试与弹窗勾选也读它。
        self.act_cache = QAction(self)
        self.act_cache.setCheckable(True)
        self.act_cache.setChecked(cache.is_enabled())

        # ---- 帮助
        m_help = bar.addMenu("帮助(&H)")
        act_readme = QAction("使用说明（README）", self)
        act_readme.triggered.connect(
            lambda: QDesktopServices.openUrl(QUrl.fromLocalFile(
                str(config.APP_DIR / "README.md"))))
        m_help.addAction(act_readme)
        m_help.addSeparator()
        act_feedback = QAction("问题反馈…", self)
        act_feedback.setToolTip(f"报告 bug 或提改进建议（发到 {feedback.AUTHOR_EMAIL}）")
        act_feedback.triggered.connect(self.on_feedback)
        m_help.addAction(act_feedback)
        m_help.addSeparator()
        act_about = QAction("关于", self)
        act_about.triggered.connect(self.on_about)
        m_help.addAction(act_about)

    def _edit_menu_actions(self, menu):
        """编辑菜单：撤销/剪切/复制/粘贴等路由到焦点所在的文本框。"""
        groups = [
            [("撤销", "Ctrl+Z", "undo"), ("重做", "Ctrl+Y", "redo")],
            [("剪切", "Ctrl+X", "cut"), ("复制", "Ctrl+C", "copy"),
             ("粘贴", "Ctrl+V", "paste")],
            [("全选", "Ctrl+A", "selectAll")],
        ]
        for i, group in enumerate(groups):
            if i:
                menu.addSeparator()
            for label, sc, meth in group:
                act = QAction(label, self)
                act.setShortcut(sc)
                act.triggered.connect(lambda _=False, m=meth: self._edit_command(m))
                menu.addAction(act)

    @staticmethod
    def _focused_editor():
        """当前焦点所在的文本控件；不是文本框就返回 None。"""
        w = QApplication.focusWidget()
        return w if isinstance(w, (QPlainTextEdit, QTextEdit)) else None

    def _edit_command(self, name: str):
        w = self._focused_editor()
        if w is not None and hasattr(w, name):
            getattr(w, name)()

    def _copy_script(self):
        code = self.editor.toPlainText()
        if not code.strip():
            self.statusBar().showMessage("编辑器还没有脚本", 3000)
            return
        QApplication.clipboard().setText(code)
        self.statusBar().showMessage("脚本全文已复制到剪贴板", 3000)

    def _zoom_editor(self, step: int):
        """step: +1 放大 / -1 缩小 / 0 重置到 11pt。"""
        if step == 0:
            pt = 11
        else:
            pt = max(7, min(28, self.editor.font().pointSize() + step))
        font = self.editor.font()
        font.setPointSize(pt)
        self.editor.setFont(font)
        self.statusBar().showMessage(f"编辑器字号：{pt}pt", 3000)

    def _open_dir(self, path):
        path.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    # ---------- 悬停浮出的「送入对话」按钮

    def _build_kp_send_button(self):
        """知识点条目右侧悬停浮出的圆形 ➜ 按钮：单击 = 送入对话。"""
        from PySide6.QtWidgets import QToolButton
        from PySide6.QtGui import QCursor

        btn = QToolButton(self.point_list.viewport())
        btn.setObjectName("kpSendBtn")
        btn.setText("➜")
        btn.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        btn.setFixedSize(26, 26)
        btn.setToolTip("送入对话，让 AI 先出方案")
        btn.setStyleSheet(
            "QToolButton#kpSendBtn {"
            " border:1px solid #cfd6df; border-radius:13px;"
            " background:#ffffff; color:#5b6472;"
            " font-size:14px; font-weight:bold; padding:0px; }"
            "QToolButton#kpSendBtn:hover {"
            " border:1px solid #4a9eff; background:#4a9eff; color:white; }"
            "QToolButton#kpSendBtn:pressed { background:#2f7fdd; }")
        btn.clicked.connect(self.on_kp_send_clicked)
        btn.hide()
        self._kp_send_btn = btn
        self._kp_hover_item = None
        self.point_list.itemEntered.connect(self._on_kp_hover)
        # 鼠标离开列表 / 滚动时收起按钮
        self.point_list.viewport().installEventFilter(self)

    def _on_kp_hover(self, item):
        """鼠标悬停到某条知识点：把按钮贴到该行右缘。"""
        self._kp_hover_item = item
        rect = self.point_list.visualItemRect(item)
        if rect.width() <= 0:
            return
        btn = self._kp_send_btn
        has_cache = item.text().startswith("💾")
        btn.setToolTip("送入对话，让 AI 先出方案"
                       + ("（已做过，命中缓存不再调 AI）" if has_cache else ""))
        btn.move(rect.right() - btn.width() - 6,
                 rect.top() + (rect.height() - btn.height()) // 2)
        btn.show()
        btn.raise_()

    def on_kp_send_clicked(self):
        """点击 ➜：等同双击该知识点，送入对话确认。"""
        item = self._kp_hover_item
        self._kp_send_btn.hide()
        if item is not None:
            self.point_list.setCurrentItem(item)
            self.on_point_activated(item)

    def on_about(self):
        """关于框：宽度按最长一行实测，避免 LaTeX 长路径被折成两行。"""
        text = self._about_text()
        box = QMessageBox(self)
        box.setWindowTitle("关于 MathViz")
        # 用应用自己的图标代替默认的 Qt 信息图标；缺失时退回普通信息图标
        if config.ICON_FILE.exists():
            from PySide6.QtGui import QIcon
            from PySide6.QtCore import QSize
            pix = QIcon(str(config.ICON_FILE)).pixmap(QSize(64, 64))
            if not pix.isNull():
                box.setIconPixmap(pix)
            else:
                box.setIcon(QMessageBox.Icon.Information)
        else:
            box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.PlainText)   # 纯文本按 \n 原样分行
        box.setText(text)
        # 文本可选中复制（查版本号/路径时有用）
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        # 反馈入口就放在这里：用户找「关于」时，往往正是遇到问题想说话的时候
        btn_feedback = box.addButton("问题反馈…", QMessageBox.ButtonRole.ActionRole)
        box.addButton("关闭", QMessageBox.ButtonRole.AcceptRole)
        # 用「文本 label 自己的字体」实测最长一行的像素宽 ——
        # 消息框文本的字号比窗口默认字体大，用窗口字体量会少算近一半，
        # 最小宽度就设小了，真实桌面上长路径照样被折（上一版踩的坑）。
        # 封顶不超过屏幕的 2/3 —— 真到那种超长路径，宁可折行也不能撑出屏幕。
        from PySide6.QtWidgets import QLabel as _QLabel
        lbl = box.findChild(_QLabel, "qt_msgbox_label")
        if lbl is None:
            lbl = next((w for w in box.findChildren(_QLabel) if w.text() == text), None)
        if lbl is not None:
            longest = max(text.splitlines(), key=len)
            text_w = lbl.fontMetrics().horizontalAdvance(longest) + 16
            max_w = self.screen().availableGeometry().width() * 2 // 3
            lbl.setWordWrap(False)
            lbl.setMinimumWidth(min(text_w, max_w))     # 布局必须给足这一行
            box.setMinimumWidth(min(text_w + 90, max_w))
        else:   # 找不到内部 label 的兜底：按窗口字体量，宁可多给也别折
            longest = max(text.splitlines(), key=len)
            max_w = self.screen().availableGeometry().width() * 2 // 3
            box.setMinimumWidth(max(min(box.fontMetrics().horizontalAdvance(longest) * 2,
                                        max_w), 420))
        box.exec()
        if box.clickedButton() is btn_feedback:
            self.on_feedback()

    def on_feedback(self):
        """打开问题反馈窗口。带上当前状态，省得对方还要解释在做什么。"""
        dlg = FeedbackDialog(self, context=self._feedback_context())
        dlg.exec()

    def _feedback_context(self) -> str:
        """反馈里自动附上的现场信息：出问题时他在干什么。"""
        parts = [f"当前标题：{self.lbl_title.text().strip() or '（未命名）'}"]
        code = self.editor.toPlainText()
        parts.append(f"编辑器脚本：{len(code.splitlines())} 行")
        parts.append("已载入课件" if self.course_text.strip() else "未载入课件")
        return "｜".join(parts)

    def _about_text(self) -> str:
        """环境自检信息：升级依赖前先看一眼版本号。"""
        try:
            import manim
            ver = manim.__version__
        except Exception:
            ver = "未安装（无法渲染）"
        latex = shutil.which("latex") or texenv.latex_dir() or "未找到"
        return ("MathViz：课件 → DeepSeek → Manim 数学动画。\n"
                f"API Key 来源：{config.api_key_source()}\n"
                f"Manim 版本：{ver}\n"
                f"LaTeX：{latex}\n"
                f"渲染工作目录：{config.RENDER_WORK_DIR}\n"
                f"问题反馈邮箱：{feedback.AUTHOR_EMAIL}")

    def _build_chat_panel(self) -> QWidget:
        """中栏：AI 策划对话 + 确认生成。有课件时基于课件，没课件也能直接聊。"""
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(4, 8, 4, 8)
        v.setSpacing(6)

        title = QLabel("💬 内容自定义与工作确认")
        title.setStyleSheet("font-weight:600;")
        v.addWidget(title)

        # 对话分页：换知识点会自动开一场新对话，旧的收进这个下拉框
        sess_row = QHBoxLayout()
        sess_row.addWidget(QLabel("对话："))
        self.combo_chat = QComboBox()
        self.combo_chat.setToolTip(
            "一场对话对应一个知识点。切换到别的知识点时，当前对话会自动收进这里，\n"
            "对话区随即清空；想回头继续，从下拉框选回来即可。也可以点 🆕 手动开一场。")
        self.combo_chat.currentIndexChanged.connect(self._on_chat_session_switch)
        sess_row.addWidget(self.combo_chat, 1)
        self.btn_new_chat = QPushButton("🆕")
        self.btn_new_chat.setFixedWidth(34)
        self.btn_new_chat.setToolTip("开一场新对话（当前的收进左边下拉框，可随时切回）")
        self.btn_new_chat.clicked.connect(self._start_new_chat)
        sess_row.addWidget(self.btn_new_chat)
        v.addLayout(sess_row)

        # 对话区与输入区之间也放一条可拖动的分割条：想让输入框高一点就往下拖
        chat_split = QSplitter()
        chat_split.setOrientation(Qt.Orientation.Vertical)
        chat_split.setChildrenCollapsible(False)

        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setStyleSheet(theme.chat_view_qss(theme.LIGHT))
        # 右键菜单：复制 / 重发 / 重生成 —— 觉得 AI 这版答得不对时，
        # 不用把整段话重新敲一遍。
        self.chat_view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.chat_view.customContextMenuRequested.connect(self._chat_menu)
        self.chat_view.setToolTip("右键：复制 / 重新编辑上一条 / 重新生成")
        chat_split.addWidget(self.chat_view)

        # 输入框：像聊天软件那样把工具栏嵌进输入框内部（底部一行），
        # 外框统一圆角边框，文字区和工具行看成一个整体
        from PySide6.QtGui import QFont
        input_box = QWidget()
        iv = QVBoxLayout(input_box)
        iv.setContentsMargins(0, 0, 0, 0)
        input_frame = QFrame()
        input_frame.setObjectName("inputFrame")
        input_frame.setStyleSheet(theme.input_frame_qss(theme.LIGHT))
        self._input_frame = input_frame      # 主题切换时要重刷这份样式
        fv = QVBoxLayout(input_frame)
        fv.setContentsMargins(6, 4, 6, 4)
        fv.setSpacing(2)

        self.chat_input = QPlainTextEdit()
        self.chat_input.setPlaceholderText(
            "想学的知识点 / 要调整的内容（Enter 发送，Shift+Enter 换行）\n"
            "没有课件也可以直接输入，例如：我想理解极限的 ε-δ 定义\n"
            "要写公式点左下角的 fx 按钮，点按钮填空即可，不用手写 LaTeX")
        self.chat_input.setMinimumHeight(70)
        self.chat_input.setStyleSheet(
            "QPlainTextEdit { border:none; background:transparent; }")
        self.chat_input.installEventFilter(self)   # 拦截 Enter 发送
        fv.addWidget(self.chat_input)

        # 公式入口：仿教科书样式的 fx 按钮（斜体衬线），嵌在输入框内左下角
        fx_row = QHBoxLayout()
        self.btn_formula = QPushButton("fx")
        fx_font = QFont("Times New Roman", 11)
        fx_font.setItalic(True)
        fx_font.setBold(True)
        self.btn_formula.setFont(fx_font)
        self.btn_formula.setFixedSize(36, 24)
        self.btn_formula.setToolTip(
            "插入数学公式：点分类按钮、填空即可拼出公式（不用写 LaTeX），\n"
            "矩阵还有专门的网格编辑器。确认后以 $…$ 形式插入对话。")
        self.btn_formula.clicked.connect(self._open_formula_editor)
        fx_row.addWidget(self.btn_formula)
        fx_row.addStretch(1)
        lbl_hint = QLabel("Enter 发送 · Shift+Enter 换行")
        lbl_hint.setStyleSheet("color:#b0b6bd; font-size:11px; border:none;")
        self._chat_hint = lbl_hint
        fx_row.addWidget(lbl_hint)
        fv.addLayout(fx_row)
        iv.addWidget(input_frame)

        # 代码修改模式：开着时，对话直接改脚本，而不是重新策划清单
        from PySide6.QtWidgets import QCheckBox
        self.chk_revise = QCheckBox("🛠 代码修改模式（AI 直接改脚本，不改呈现清单）")
        self.chk_revise.setToolTip(
            "适合\"画面效果不对\"的情况：矩阵排成了死板的数字行、某步节奏太快、"
            "配色刺眼、布局重叠等。\n"
            "开启后输入的要求会直接作用在右上角编辑器里的脚本上；\n"
            "想改\"讲什么内容\"（增删知识点），请关掉它再发消息。")
        iv.addWidget(self.chk_revise)

        row = QHBoxLayout()
        self.btn_send = QPushButton("发送 ➤")
        self.btn_send.clicked.connect(self.on_send)
        self.btn_clear = QPushButton("🧹 清空")
        self.btn_clear.clicked.connect(self.on_clear)
        self.btn_clear.setToolTip(
            "重置整个工作区，回到刚打开时的状态：\n"
            "课件、知识点、对话、脚本、成片全部清空。\n"
            "已渲染并归档到 media/ 的文件不会被删除。")
        self.btn_generate = QPushButton("✅ 确认，生成脚本")
        self.btn_generate.setEnabled(False)
        self.btn_generate.clicked.connect(self.on_generate)
        self.btn_generate.setToolTip(
            "按对话里确认的「呈现清单」生成动画脚本；\n"
            "若左侧选中了知识点，则以该知识点为标题与主题。")
        row.addWidget(self.btn_send)
        row.addWidget(self.btn_clear)
        row.addWidget(self.btn_generate, 1)
        iv.addLayout(row)

        chat_split.addWidget(input_box)
        chat_split.setSizes([380, 210])
        v.addWidget(chat_split, 1)
        return panel

    def eventFilter(self, obj, event):
        """聊天输入框：Enter 直接发送，Shift+Enter 才换行。"""
        chat = getattr(self, "chat_input", None)   # UI 未建完时可能还不存在
        if (obj is chat
                and event.type() == QEvent.Type.KeyPress
                and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
                and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier)):
            self.on_send()
            return True
        # 知识点列表：鼠标离开或滚动时收起悬浮的 ➜ 按钮
        if (hasattr(self, "_kp_send_btn")
                and obj is self.point_list.viewport() and event.type() in (
                    QEvent.Type.Leave, QEvent.Type.Wheel)):
            self._kp_send_btn.hide()
        # 视频画面：双击切换播放器模式；窗口缩放时 ⤢ 按钮贴住右上角
        if hasattr(self, "video_widget") and obj is self.video_widget:
            if event.type() == QEvent.Type.MouseButtonDblClick:
                # 已在大屏里就退出，否则进入 —— 与常见播放器的双击全屏一致
                if self.act_player_mode.isChecked():
                    self._exit_player_mode()
                else:
                    self._enter_player_mode()
                return True
            if event.type() == QEvent.Type.Resize:
                self._place_expand_btn()
        # 全屏窗口：Esc 退出；直接关窗（点 ×）也要把画面还回预览页，
        # 否则视频会跟着临时窗口一起消失，预览区只剩一个空框。
        fs = getattr(self, "_fs_window", None)
        if fs is not None and obj is fs:
            if event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Escape:
                self._exit_fullscreen()
                return True
            if event.type() == QEvent.Type.Close:
                self._exit_fullscreen()
        return super().eventFilter(obj, event)

    def _place_expand_btn(self):
        """放大按钮贴视频左上角（留 8px 边距）。"""
        self.btn_expand.move(8, 8)

    def _enter_player_mode(self):
        """进播放器模式（⤢ 按钮 / 双击画面共用）。"""
        self.act_player_mode.setChecked(True)   # 触发 toggled → 切换

    def _build_preview_page(self):
        """预览页：视频画面 + 播放控制条 + 兜底入口。"""
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(6, 6, 6, 6)
        v.setSpacing(6)
        # 全屏播放要把画面整体搬进一个临时顶层窗口，退出时再插回这个布局的原位
        self._preview_v = v
        self._preview_page = page

        # 视频画面：用 VideoCanvas（内部是 QGraphicsVideoItem）而不是 QVideoWidget。
        # QVideoWidget 带一层原生渲染表面，会吞掉叠在它附近的任何普通控件 ——
        # 右上角的 ⤢ 按钮画不出来、tooltip 也退化成看不见字的黑条。换成图形项
        # 之后视频只是场景里的一个图元，叠加控件和提示框全部恢复正常。
        self.video_container = QWidget()
        cv = QVBoxLayout(self.video_container)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(0)

        self.video_widget = VideoCanvas()
        cv.addWidget(self.video_widget, 1)
        v.addWidget(self.video_container, 1)

        # 视频左上角的放大按钮（灰色的对角箭头，指向左下-右上方向的反向即"撑开画面"）：
        # 点击/双击画面都进播放器模式 —— 想看大屏时不必去菜单里翻。
        # 图标用 SVG 自绘而不是字符字形：同一个箭头字符在不同系统字体下
        # 形状差异极大（有的缺字、有的字形歪），而它是按钮上唯一的内容。
        self.btn_expand = icons.HoverIconButton(icons.expand_icon,
                                                parent=self.video_container)
        self.btn_expand.setObjectName("btn_expand")
        self.btn_expand.setFixedSize(32, 28)
        self.btn_expand.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_expand.setToolTip("进入播放器模式（大屏看片，也可双击画面）")
        self.btn_expand.setIconSize(QSize(18, 18))
        self.btn_expand.setStyleSheet(
            "QPushButton{background:rgba(28,28,28,120);"
            "border:1px solid rgba(255,255,255,60);border-radius:5px;}"
            "QPushButton:hover{background:rgba(70,70,70,205);"
            "border:1px solid rgba(255,255,255,130);}")
        self.btn_expand.clicked.connect(self._enter_player_mode)
        self.video_widget.installEventFilter(self)   # resize / 双击都走 eventFilter
        self._place_expand_btn()

        bar = QHBoxLayout()
        self.btn_play = QPushButton("▶ 播放")
        self.btn_play.setEnabled(False)
        self.btn_play.clicked.connect(self._toggle_play)
        self.btn_replay = QPushButton("⏮ 重播")
        self.btn_replay.setEnabled(False)
        self.btn_replay.clicked.connect(self._replay)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setEnabled(False)
        self.slider.setRange(0, 0)
        self.slider.sliderPressed.connect(lambda: setattr(self, "_seeking", True))
        self.slider.sliderReleased.connect(self._on_seek_released)
        self.lbl_time = QLabel("00:00 / 00:00")

        # 低频操作收进「⋯」菜单。控制条上只留真正会被反复点的三个（播放 / 重播 / 进度）：
        # 打开位置、导出 GIF、导出关键帧这类动作一支片子也就点一两次，
        # 挤成一排反而把播放控件压扁，还让"能不能播"这件事变得难找。
        self.btn_more = QPushButton("⋯")
        self.btn_more.setFixedWidth(32)
        self.btn_more.setToolTip("更多操作：打开位置 / 导出")
        self.btn_more.setEnabled(False)
        self.m_media = QMenu(self)
        self.act_open_ext = QAction("🖥 用系统播放器打开", self)
        self.act_open_ext.triggered.connect(lambda: self._open_external())
        self.act_open_folder = QAction("📂 打开所在文件夹", self)
        self.act_open_folder.triggered.connect(self._open_folder)
        self.act_gif = QAction("🎞 导出 GIF…\tCtrl+Shift+G", self)
        self.act_gif.setToolTip(
            "把成片转成 GIF（默认取前 20 秒、480px 宽），方便插 PPT / 课件 / 微信。\n"
            "存到 media/ 同名目录，不会覆盖原视频。")
        self.act_gif.triggered.connect(self.on_export_gif)
        self.act_frames = QAction("🖼 导出关键帧 PNG…\tCtrl+Shift+P", self)
        self.act_frames.setToolTip(
            "从成片里等间隔抽 12 张 PNG（做插图、印讲义）。\n"
            "存到 media/<知识点>-<时间>-关键帧/ 目录。")
        self.act_frames.triggered.connect(self.on_export_frames)
        self.act_handout = QAction("📄 导出讲义 PDF…\tCtrl+Shift+H", self)
        self.act_handout.setToolTip(
            "把脚本里的中文解说 + 4 张关键帧拼成一页 A4 讲义（PDF）。\n"
            "复习、打印、发给同学都比视频轻。")
        self.act_handout.triggered.connect(self.on_export_handout)
        self.m_media.addAction(self.act_open_ext)
        self.m_media.addAction(self.act_open_folder)
        self.m_media.addSeparator()
        self.m_media.addAction(self.act_gif)
        self.m_media.addAction(self.act_frames)
        self.m_media.addAction(self.act_handout)
        self.m_media.addSeparator()
        # A-B 循环：教学片里"这一段我没看懂"要反复看，手动拖回去太累。
        # 入口藏在菜单里是因为它一支片子也就设一两次，摊在控制条上会挤掉播放控件。
        self.act_loop_a = QAction("⟲ 把当前位置设为循环起点 A", self)
        self.act_loop_a.triggered.connect(lambda: self._set_loop_point("a"))
        self.act_loop_b = QAction("⟳ 把当前位置设为循环终点 B", self)
        self.act_loop_b.triggered.connect(lambda: self._set_loop_point("b"))
        self.act_loop_clear = QAction("✕ 取消 A-B 循环", self)
        self.act_loop_clear.setEnabled(False)
        self.act_loop_clear.triggered.connect(self._clear_loop)
        for a in (self.act_loop_a, self.act_loop_b, self.act_loop_clear):
            self.m_media.addAction(a)
        self.m_media.addSeparator()
        self.act_step_back = QAction("⏪ 后退一帧（,）", self)
        self.act_step_back.triggered.connect(lambda: self._step_frame(-1))
        self.act_step_fwd = QAction("⏩ 前进一帧（.）", self)
        self.act_step_fwd.triggered.connect(lambda: self._step_frame(+1))
        self.m_media.addAction(self.act_step_back)
        self.m_media.addAction(self.act_step_fwd)
        self.btn_more.setMenu(self.m_media)

        bar.addWidget(self.btn_play)
        bar.addWidget(self.btn_replay)
        bar.addWidget(self.slider, 1)
        bar.addWidget(self.lbl_time)

        # 倍速：教学片最常用的是"慢一点看清楚"，所以 0.5x/0.75x 放在前面。
        self.combo_speed = QComboBox()
        for r in (0.5, 0.75, 1.0, 1.25, 1.5, 2.0):
            self.combo_speed.addItem(f"{r:g}x", r)
        self.combo_speed.setCurrentIndex(self.combo_speed.findData(1.0))
        self.combo_speed.setFixedWidth(66)
        self.combo_speed.setToolTip(
            "播放倍速（只影响内置播放器，不改文件）。\n"
            "看不清楚的地方切 0.5x 慢放，复习已懂的段落切 1.5~2x 快进。")
        self.combo_speed.currentIndexChanged.connect(self._on_speed_changed)
        bar.addWidget(self.combo_speed)

        self.btn_fs = QPushButton("⛶")
        self.btn_fs.setFixedWidth(32)
        self.btn_fs.setEnabled(False)
        self.btn_fs.setToolTip("全屏播放（F11）· Esc 退出")
        self.btn_fs.clicked.connect(self._toggle_fullscreen)
        bar.addWidget(self.btn_fs)

        bar.addWidget(self.btn_more)
        v.addLayout(bar)

        self.lbl_video = QLabel("尚未渲染视频")
        self.lbl_video.setWordWrap(True)
        v.addWidget(self.lbl_video)

        # 播放器模式的目录条：平时隐藏，切到播放器模式时出现在视频下方
        # （朋友建议的"上面视频、下面知识点目录"形态；不 reparent 任何控件，
        #   退回工作台只是 hide/show，零风险）
        self.player_bar = QWidget()
        pb = QHBoxLayout(self.player_bar)
        pb.setContentsMargins(0, 0, 0, 0)
        self.btn_back_workbench = QPushButton("◀ 返回工作台")
        self.btn_back_workbench.setToolTip("切回「左输入右输出」的工作台布局")
        self.btn_back_workbench.clicked.connect(self._exit_player_mode)
        pb.addWidget(self.btn_back_workbench)
        pb.addWidget(QLabel("  目录："))
        self.player_nav_layout = QHBoxLayout()
        self.player_nav_layout.setSpacing(4)
        pb.addLayout(self.player_nav_layout, 1)
        self.player_bar.hide()
        v.addWidget(self.player_bar)
        return page

    def _build_media(self):
        """播放器核心：**必须**把画面输出接到 VideoCanvas 的 video_item，
        否则等于对着空气放映。"""
        self.current_video: str | None = None
        self._external_opened = False
        self._seeking = False
        self._loop_a: int | None = None      # A-B 循环的两个端点（毫秒）
        self._loop_b: int | None = None
        self._fs_window = None               # 全屏播放时的临时顶层窗口
        self._fallback_timer = QTimer(self)
        self._fallback_timer.setSingleShot(True)
        self._fallback_timer.setInterval(3500)
        self._fallback_timer.timeout.connect(self._check_playback_started)

        self.audio_output = QAudioOutput()
        self.player = QMediaPlayer()
        self.player.setAudioOutput(self.audio_output)
        self.player.setVideoOutput(self.video_widget.video_item())   # ← 缺了这一句就是黑框
        self.audio_output.setVolume(1.0)
        # 成片默认循环播放（教学视频反复看是常态）
        try:
            self.player.setLoops(QMediaPlayer.Loops.Infinite)
        except Exception:
            pass   # 旧版 Qt 没有该接口，退化为单次播放

        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self._on_duration_changed)
        self.player.errorOccurred.connect(self._on_player_error)
        self.player.mediaStatusChanged.connect(self._on_media_status)

    # ---------- 播放控制

    @staticmethod
    def _fmt_ms(ms: int) -> str:
        s = max(0, ms) // 1000
        return f"{s // 60:02d}:{s % 60:02d}"

    def _load_video(self, path: str):
        """加载并自动播放一段成片；Qt 播不动时自动交给系统播放器。"""
        self.current_video = str(path)
        self._external_opened = False
        self.lbl_video.setText(f"🎞 {os.path.basename(str(path))}")
        self.btn_play.setEnabled(True)
        self.btn_replay.setEnabled(True)
        self._apply_media_enabled()
        self.player.stop()
        self.player.setSource(QUrl.fromLocalFile(self.current_video))
        self.player.play()
        self._fallback_timer.start()   # 2.5s 后确认是否真的动起来了

    def _toggle_play(self):
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            if self.player.playbackState() == QMediaPlayer.PlaybackState.StoppedState \
                    and self.player.position() >= max(1, self.player.duration()):
                self.player.setPosition(0)
            self.player.play()

    def _replay(self):
        self.player.setPosition(0)
        self.player.play()

    def _on_seek_released(self):
        self._seeking = False
        self.player.setPosition(self.slider.value())

    def _on_position_changed(self, pos: int):
        if self._loop_active() and pos >= self._loop_b and not self._seeking:
            self.player.setPosition(self._loop_a)   # 到 B 就跳回 A，不用手动拖
            return
        if not self._seeking:
            self.slider.setValue(pos)
        self._update_time_label(pos, self.player.duration())

    def _on_duration_changed(self, dur: int):
        self.slider.setEnabled(dur > 0)
        self.slider.setRange(0, dur)
        self._update_time_label(self.player.position(), dur)

    def _update_time_label(self, pos: int, dur: int):
        txt = f"{self._fmt_ms(pos)} / {self._fmt_ms(dur)}"
        rate = self.combo_speed.currentData() or 1.0
        if abs(rate - 1.0) > 1e-6:
            txt += f" · {rate:g}x"
        if self._loop_active():
            txt += f" · ⟲{self._fmt_ms(self._loop_a)}~{self._fmt_ms(self._loop_b)}"
        self.lbl_time.setText(txt)

    # ---------- 播放增强：倍速 / 逐帧 / 键盘 / A-B 循环 / 全屏

    # "一帧"按 30fps 算：manim 成片常见 15/30/60fps，
    # 这里只是给逐帧一个够细的步长，不追求与实际帧边界对齐。
    FRAME_MS = 33

    def _on_speed_changed(self):
        rate = self.combo_speed.currentData() or 1.0
        try:
            self.player.setPlaybackRate(float(rate))
        except Exception:
            pass
        self._update_time_label(self.player.position(), self.player.duration())

    def _step_frame(self, direction: int):
        """逐帧：先暂停，再挪一个"一帧"的步长。"""
        if not self.current_video:
            return
        self.player.pause()
        pos = max(0, min(self.player.duration(),
                         self.player.position() + direction * self.FRAME_MS))
        self.player.setPosition(pos)
        self.slider.setValue(pos)

    def _set_loop_point(self, which: str):
        pos = self.player.position()
        if which == "a":
            self._loop_a = pos
        else:
            self._loop_b = pos
            if self._loop_a is not None and pos < self._loop_a:
                self._loop_a, self._loop_b = pos, self._loop_a   # 设反了就换回来
        self.act_loop_clear.setEnabled(True)
        self._log(f"[循环] A={self._fmt_ms(self._loop_a or 0)} "
                  f"B={self._fmt_ms(self._loop_b or 0)}（播放到 B 自动跳回 A）")
        self._update_time_label(pos, self.player.duration())

    def _clear_loop(self):
        self._loop_a = self._loop_b = None
        self.act_loop_clear.setEnabled(False)
        self._update_time_label(self.player.position(), self.player.duration())

    def _loop_active(self) -> bool:
        return self._loop_a is not None and self._loop_b is not None \
            and self._loop_b > self._loop_a

    def _build_media_shortcuts(self):
        """播放快捷键。

        用 WindowShortcut 而不是挂在视频上（那样必须先点一下画面才生效，很难发现），
        但在回调里挡掉"焦点正在输入类控件里"的情况：编辑器里按空格是要打空格，
        列表上按方向键是要换条目 —— 不能让播放器抢走。
        """
        pairs = [
            ("Space", "play"), ("Left", "-5s"), ("Right", "+5s"),
            (",", "-frame"), (".", "+frame"),
            ("Up", "vol+"), ("Down", "vol-"), ("F11", "fullscreen"),
        ]
        for key, kind in pairs:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(lambda k=kind: self._media_hotkey(k))

    def _media_hotkey(self, kind: str):
        fw = QApplication.focusWidget()
        if isinstance(fw, (QPlainTextEdit, QTextEdit, QLineEdit, QComboBox,
                           QSpinBox, QCheckBox, QSlider, QAbstractItemView)):
            return          # 焦点在输入/选择类控件里，这些键归它自己
        if kind == "fullscreen":
            self._toggle_fullscreen()
            return
        if not self.current_video:
            return
        if kind == "play":
            self._toggle_play()
        elif kind in ("-5s", "+5s"):
            delta = -5000 if kind == "-5s" else 5000
            self.player.setPosition(
                max(0, min(self.player.duration(), self.player.position() + delta)))
        elif kind in ("-frame", "+frame"):
            self._step_frame(-1 if kind == "-frame" else 1)
        elif kind in ("vol+", "vol-"):
            v = self.audio_output.volume() + (0.1 if kind == "vol+" else -0.1)
            self.audio_output.setVolume(max(0.0, min(1.0, v)))

    def _toggle_fullscreen(self):
        """把画面整体搬进一个顶层窗口铺满屏幕；退出时插回预览页原位。

        为什么不 reparent 播放器核心：QMediaPlayer 与 VideoCanvas 的关系不随父控件
        变化，搬的是外壳（video_container），视频照常播。
        """
        if getattr(self, "_fs_window", None) is not None:
            self._exit_fullscreen()
            return
        if not self.current_video:
            return
        win = QWidget(None)
        win.setWindowTitle("MathViz — 全屏播放（Esc 退出）")
        win.setStyleSheet("background:#000000;")
        lay = QVBoxLayout(win)
        lay.setContentsMargins(0, 0, 0, 0)
        self.btn_expand.hide()          # 全屏时"进入播放器模式"没有意义
        self.video_container.setParent(win)
        lay.addWidget(self.video_container, 1)
        tip = QLabel("空格 播放/暂停 · ←→ 快退快进 · , . 逐帧 · Esc 退出全屏")
        tip.setStyleSheet("color:#7a7a7a; background:#000000; padding:4px;")
        tip.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(tip)
        win.installEventFilter(self)
        win.showFullScreen()
        self._fs_window = win
        self.btn_fs.setText("⛗")

    def _exit_fullscreen(self):
        win = getattr(self, "_fs_window", None)
        if win is None:
            return
        self._fs_window = None
        try:
            win.removeEventFilter(self)
        except Exception:
            pass
        # Qt 的规矩：换父控件会让 widget 变隐藏（哪怕之前是可见的），
        # 所以搬回预览页之后必须显式 show()，否则预览区只剩一个空框。
        self.video_container.setParent(None)
        self._preview_v.insertWidget(0, self.video_container, 1)
        self.video_container.show()
        self.btn_expand.show()
        self._place_expand_btn()
        win.deleteLater()
        self.btn_fs.setText("⛶")

    def _on_state_changed(self, state):
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play.setText("⏸ 暂停" if playing else "▶ 播放")

    def _on_media_status(self, status):
        if status == QMediaPlayer.MediaStatus.InvalidMedia:
            self._log("[播放] 内置播放器无法解码该视频，自动改用系统播放器打开。")
            self._open_external(auto=True)

    def _on_player_error(self, error, error_string: str):
        # 常见原因：系统缺 Qt 多媒体解码后端。成片本身没坏，交给系统播放器兜底。
        self._log(f"[播放] 内置播放器无法播放（{error_string}）。已改用系统播放器。")
        self._open_external(auto=True)

    def _check_playback_started(self):
        """Qt 播放器没能启动时的兜底：宁可多开一个窗口，也不让预览变成摆设。"""
        if self.player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._log("[播放] 内置播放器迟迟未能启动，自动改用系统播放器打开。")
            self._open_external(auto=True)

    def _open_external(self, auto: bool = False):
        """用系统播放器打开成片。

        auto=True 表示"内置播放器播不动"时的自动兜底 —— 那种情况只托付一次，
        免得反复弹窗；用户手动点按钮则每次都真的打开。
        （以前两者共用一个开关：自动兜底用掉之后，手动点击就变成"点了没反应"。）
        """
        self.player.pause()   # 让出文件句柄，避免播放器打不开被占用的文件
        if not self.current_video:
            return False
        if auto and getattr(self, "_external_opened", False):
            return False
        path = self.current_video
        if not os.path.exists(path):
            self._log(f"[播放] 成片已不在原处：{path}")
            QMessageBox.warning(self, "打不开成片",
                                f"文件不存在或已被移动：\n{path}")
            return False
        ok, how = _launch_file(path)
        if ok:
            self._external_opened = True
            self._log(f"[播放] 已调用系统播放器（{how}）")
        else:
            self._log(f"[播放] 系统播放器调用失败：{how}")
            QMessageBox.warning(
                self, "无法调用系统播放器",
                f"没能打开：\n{path}\n\n原因：{how}\n\n"
                "可以走「文件 → 打开成片文件夹」手动双击播放。")
        return ok

    def _open_folder(self):
        if not self.current_video:
            return
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(config.OUTPUT_MEDIA_DIR)))

    def _refresh_key_status(self):
        src = config.api_key_source()
        if config.get_api_key():
            self.lbl_key.setText(f"🔑 DeepSeek Key：已就绪（{src}）")
        else:
            self.lbl_key.setText("🔑 DeepSeek Key：未配置！请设环境变量 DEEPSEEK_API_KEY 或建 .env")

    # ---------- 工具

    def _log(self, msg: str):
        self.log_view.appendPlainText(msg)
        self.statusBar().showMessage(msg[-120:], 5000)

    def _set_busy(self, busy: bool, hint: str = ""):
        self._busy = busy
        for b in (self.drop_zone, self.btn_extract, self.btn_generate,
                  self.btn_render, self.btn_send,
                  self.btn_clear, self.chk_revise,
                  self.combo_chat, self.btn_new_chat, self.btn_formula,
                  self.btn_more, self.btn_batch, self.cmb_version,
                  self.btn_ver_revert, self.btn_ver_diff, self.btn_ver_save,
                  self.btn_qc, self.chk_range, self.spin_from, self.spin_to):
            b.setEnabled(not busy)
        for a in (self.act_extract, self.act_generate,
                  self.act_render, self.act_render_hd_once, self.act_quickcheck):
            a.setEnabled(not busy)
        if not busy:
            self.btn_clear.setEnabled(True)   # 清空按钮不受"有没有内容"限制
            self._refresh_buttons()
            # 版本下拉与三个按钮在 busy 时被整体禁用，恢复后按"有没有选中版本"
            # 重新判定，避免出现"没选版本也能点退回"的状态
            self.cmb_version.setEnabled(True)
            self._on_version_selected()
        if hint:
            self.statusBar().showMessage(hint)

    def _apply_media_enabled(self):
        """「有没有成片」这一个真相源，统一同步给预览菜单与菜单栏的导出项。

        以前按钮和菜单各判一次，出现过"菜单能点、按钮却灰着"的状态打架；
        现在所有成片相关的入口都从这里取，谁也别自作主张。
        """
        has_video = bool(getattr(self, "current_video", None))
        for a in (self.act_open_ext, self.act_open_folder,
                  self.act_gif, self.act_frames, self.act_handout,
                  self.act_export_gif, self.act_export_frames,
                  self.act_export_handout):
            a.setEnabled(has_video)
        # 倍速 / 全屏 / 循环：跟着"有没有成片"走，没有片子就是灰的
        for w in (self.combo_speed, self.btn_fs):
            w.setEnabled(has_video)
        for a in (self.act_loop_a, self.act_loop_b,
                  self.act_step_back, self.act_step_fwd):
            a.setEnabled(has_video)
        if not has_video:
            self.act_loop_clear.setEnabled(False)
        # 导出要跑 ffmpeg，渲染/转写期间照样得锁住，避免对同一个 mp4 下手
        self.btn_more.setEnabled(has_video and not getattr(self, "_busy", False))
        return has_video

    def _refresh_pacing(self):
        """把「预计成片多少秒」刷到渲染按钮旁边。

        我们不要求用户自己填视频时长 —— 那是普通人最难把握的东西，节奏交给提示词里
        写死的「中等偏慢」口径（45~80 秒）。但按下渲染之前，他有权知道 AI 这次排了
        多久：估算 = 脚本里所有 play 的 run_time 与 wait 之和，够用来判断快慢。
        """
        secs, hints = validator.pacing_report(self.editor.toPlainText())
        plain = "border:none; background:transparent;"
        self._refresh_play_count()
        if not secs:
            self.lbl_pacing.setText("预计时长：—")
            self.lbl_pacing.setStyleSheet(f"color:#8a8f98; {plain}")
            self.lbl_pacing.setToolTip(hints[0] if hints else "还没有可估算的脚本")
            return
        self.lbl_pacing.setText(f"预计成片 ~{secs:.0f} 秒")
        if hints:
            self.lbl_pacing.setStyleSheet(f"color:#b2500a; font-weight:600; {plain}")
            self.lbl_pacing.setToolTip("目标：中等偏慢 45~80 秒\n\n"
                                       + "\n".join(f"• {h}" for h in hints))
        else:
            self.lbl_pacing.setStyleSheet(f"color:#3b7a3b; {plain}")
            self.lbl_pacing.setToolTip(
                "节奏落在「中等偏慢」目标区间（45~80 秒）\n"
                "估算 = 脚本里所有 play 的 run_time 与 wait 之和")

    # ---------- 画质 / 分段 / 快检（都是"省一次完整渲染"的手段）

    def _current_quality(self) -> str:
        return self.combo_quality.currentData() or "low"

    def _on_quality_changed(self):
        QSettings("MathViz", "MathViz").setValue("render_quality",
                                                 self._current_quality())
        self._apply_quality_ui()

    def _apply_quality_ui(self):
        """画质档位变化时同步按钮与菜单文案（只有一个渲染入口，跟着档位走）。"""
        q = self._current_quality()
        label = renderer.QUALITY_LABELS.get(q, q)
        self.btn_render.setText(f"🎬 渲染（{label}）")
        self.act_render.setText(f"🎬 渲染（{label}）")

    def _apply_range_enabled(self):
        on = self.chk_range.isChecked()
        self.spin_from.setEnabled(on)
        self.spin_to.setEnabled(on)

    def _refresh_play_count(self):
        """按脚本静态统计"动画段"数，给分段渲染的范围框定上限。"""
        n = renderer.count_plays(self.editor.toPlainText())
        self.lbl_plays.setText(f"（共 {n} 段）" if n else "（共 — 段）")
        top = max(1, n)
        self.spin_from.setRange(1, top)
        self.spin_to.setRange(1, top)
        if not self.chk_range.isChecked():
            self.spin_from.setValue(1)
            self.spin_to.setValue(top)

    def _current_anim_range(self) -> tuple[int, int] | None:
        if not self.chk_range.isChecked():
            return None
        a, b = self.spin_from.value(), self.spin_to.value()
        if a > b:
            a, b = b, a
        return (a, b)

    def on_quickcheck(self):
        code = self.editor.toPlainText().strip()
        if not code:
            QMessageBox.information(self, "提示", "编辑器里还没有脚本")
            return
        if not tex_ready(self):   # 没有 LaTeX 就别白跑一趟
            return
        if not self.current_scene_name:
            self.current_scene_name = f"KP{time.strftime('%m%d_%H%M%S')}"
            self.lbl_scene.setText(f"Scene: {self.current_scene_name}")
        config.ensure_dirs()

        def done(ok, dest, msg):
            self.render_bar.hide()
            if ok and dest:
                self._log(f"[快检] {msg}")
                self._show_quickcheck(dest)
            else:
                self._show_render_failure(msg, title="版式快检未成功")

        w = QuickCheckWorker(code, self.current_scene_name,
                             layout=self._current_layout())
        w.progress.connect(self._on_render_progress)
        self.render_bar.setFormat("快检 %p%")
        self._run_worker(w, done,
                         lambda e: (self.render_bar.hide(),
                                    self._show_render_failure(e, title="快检错误")))
        self.tabs.setCurrentIndex(1)

    def _show_quickcheck(self, frames_dir: str):
        """把快检抽出来的定格图摊开给人看。

        不做拼图：文字压没压在一起这种事，把图缩小拼成一排反而看不清，
        所以按原比例摊在网格里，每张下面标上是第几帧、大约在几秒。
        """
        d = Path(frames_dir)
        pngs = sorted(p for p in d.glob("*.png")) if d.exists() else []
        if not pngs:
            QMessageBox.information(self, "快检", "没能抽出定格图")
            return
        dlg = QDialog(self)
        dlg.setWindowTitle("版式快检 — 定格图")
        dlg.resize(1100, 720)
        v = QVBoxLayout(dlg)
        v.addWidget(QLabel(
            f"共 {len(pngs)} 张定格（低帧率小分辨率渲染，只为看版式）。\n"
            "重点看：文字有没有压在一起、有没有跑出画面、公式有没有被裁掉。"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        grid = QGridLayout(body)
        grid.setSpacing(8)
        cols = 3
        for i, p in enumerate(pngs):
            cell = QVBoxLayout()
            lbl = QLabel()
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            pm = QPixmap(str(p))
            if not pm.isNull():
                lbl.setPixmap(pm.scaledToWidth(330, Qt.TransformationMode.SmoothTransformation))
            cap = QLabel(f"{i + 1}/{len(pngs)}")
            cap.setAlignment(Qt.AlignmentFlag.AlignCenter)
            cap.setStyleSheet("color:#8a8f98;")
            cell.addWidget(lbl)
            cell.addWidget(cap)
            holder = QWidget()
            holder.setLayout(cell)
            grid.addWidget(holder, i // cols, i % cols)
        scroll.setWidget(body)
        v.addWidget(scroll, 1)

        row = QHBoxLayout()
        btn_open = QPushButton("📂 打开图片文件夹")
        btn_open.clicked.connect(lambda: self._open_dir(d))
        row.addWidget(btn_open)
        row.addStretch(1)
        btn_ok = QPushButton("关闭")
        btn_ok.setDefault(True)
        btn_ok.clicked.connect(dlg.accept)
        row.addWidget(btn_ok)
        v.addLayout(row)
        dlg.exec()

    def _on_render_progress(self, pct: int):
        """状态栏进度条：manim 的逐动画进度换算出的总体百分比。"""
        self.render_bar.setVisible(True)
        self.render_bar.setValue(max(0, min(100, int(pct))))

    # ---------- 对话消息操作（右键菜单）

    def _last_user_index(self) -> int:
        """最后一条"我说的"在气泡列表里的下标；没有就返回 -1。"""
        for i in range(len(self.chat_bubbles) - 1, -1, -1):
            if self.chat_bubbles[i][0] == "user":
                return i
        return -1

    def _last_assistant_text(self) -> str:
        for role, text in reversed(self.chat_bubbles):
            if role == "assistant":
                return text
        return ""

    def _truncate_after_user(self):
        """把最后一组对话（我说的 + 之后的所有回复/提示）从气泡与历史里抹掉。

        两边要一起删：chat_history 是喂给 AI 的，chat_bubbles 是画出来的，
        只删一边会出现"界面上看不见了，AI 其实还记得"的鬼故事。
        """
        idx = self._last_user_index()
        if idx < 0:
            return ""
        text = self.chat_bubbles[idx][1]
        del self.chat_bubbles[idx:]
        hu = -1
        for i, h in enumerate(self.chat_history):
            if h.get("role") == "user":
                hu = i
        if hu >= 0:
            del self.chat_history[hu:]
        return text

    def _chat_menu(self, pos):
        bubbles = self.chat_bubbles
        has_user = self._last_user_index() >= 0
        menu = QMenu(self)

        act_copy_last = QAction("📋 复制最后一条回复", self)
        act_copy_last.setEnabled(bool(self._last_assistant_text()))
        act_copy_last.triggered.connect(self._copy_last_reply)
        menu.addAction(act_copy_last)

        act_copy_all = QAction("📋 复制整段对话", self)
        act_copy_all.setEnabled(bool(bubbles))
        act_copy_all.triggered.connect(self._copy_all_chat)
        menu.addAction(act_copy_all)
        menu.addSeparator()

        act_edit = QAction("✏️ 把上一条提问放回输入框重发", self)
        act_edit.setEnabled(has_user)
        act_edit.setToolTip("删掉这一组对话，把原文填回输入框，改完直接发送")
        act_edit.triggered.connect(self._edit_last_message)
        menu.addAction(act_edit)

        act_regen = QAction("🔄 重新生成最后一条回复", self)
        act_regen.setEnabled(has_user and not self.chk_revise.isChecked())
        act_regen.setToolTip("同一句话让 AI 再答一次（代码修改模式下不可用）")
        act_regen.triggered.connect(self._regenerate_last)
        menu.addAction(act_regen)

        act_del = QAction("🗑 删除最后一组对话", self)
        act_del.setEnabled(has_user)
        act_del.triggered.connect(self._delete_last_group)
        menu.addAction(act_del)

        menu.exec(self.chat_view.viewport().mapToGlobal(pos))

    def _copy_last_reply(self):
        text = self._last_assistant_text()
        if not text:
            return
        QApplication.clipboard().setText(text)
        self.statusBar().showMessage("已复制最后一条回复", 3000)

    def _copy_all_chat(self):
        lines = []
        for role, text in self.chat_bubbles:
            who = {"user": "我", "assistant": "AI", "system": "—"}.get(role, role)
            lines.append(f"{who}：{text}")
        QApplication.clipboard().setText("\n\n".join(lines))
        self.statusBar().showMessage(f"已复制 {len(self.chat_bubbles)} 条对话", 3000)

    def _edit_last_message(self):
        text = self._truncate_after_user()
        if not text:
            return
        self._replay_chat_bubbles()
        self.chat_input.setPlainText(text)
        self.chat_input.setFocus()
        cur = self.chat_input.textCursor()
        cur.movePosition(cur.MoveOperation.End)
        self.chat_input.setTextCursor(cur)
        self._refresh_buttons()

    def _delete_last_group(self):
        if not self._truncate_after_user():
            return
        self._replay_chat_bubbles()
        self.chat_plan = ""      # 呈现清单是 AI 给的，删了回复就不该还挂着
        self._refresh_buttons()
        self._log("[对话] 已删除最后一组对话")

    def _regenerate_last(self):
        idx = self._last_user_index()
        if idx < 0:
            return
        if not config.get_api_key():
            QMessageBox.warning(self, "未配置 Key",
                                "重新生成需要 DeepSeek API Key，请先配置。")
            return
        text = self.chat_bubbles[idx][1]
        del self.chat_bubbles[idx + 1:]      # 只丢掉回复，提问留着
        hu = -1
        for i, h in enumerate(self.chat_history):
            if h.get("role") == "user":
                hu = i
        if hu >= 0:
            del self.chat_history[hu + 1:]
        self._replay_chat_bubbles()
        self._log("[对话] 重新生成最后一条回复……")
        self._send_message(text, already_shown=True)

    # ---------- 界面主题与字号

    def _apply_theme(self, name: str | None = None, size: str | None = None):
        """切换浅色 / 深色 / 跟随系统，并同步界面字号。

        两件事必须一起做：全局 QSS 只管得了标准控件，
        而列表项、对话气泡、投放区、代码高亮这些是写死在各自 setStyleSheet 里的，
        得按新配色逐个重写（theme 模块负责提供这些片段）。

        name 可以是 "light" / "dark" / "system"。跟系统时这里只记模式，
        真正用到的是 theme.resolve() 按当前系统配色解析出来的那套。
        """
        st = QSettings("MathViz", "MathViz")
        mode = name or st.value("ui_theme", "light", type=str)
        size = size or st.value("ui_font", "normal", type=str)
        p = theme.resolve(mode)
        self._theme_mode = mode
        app = QApplication.instance()
        if app is not None:
            base_family = getattr(self, "_base_font_family", "") or app.font().family()
            if not getattr(self, "_base_font_family", ""):
                self._base_font_family = base_family
            app.setFont(theme.app_font(base_family, size))
            app.setStyleSheet(theme.app_qss(p))
        self._bc = theme.bubble_colors(p)
        self._palette = p
        for lst in (self.point_list, self.history_list):
            lst.setStyleSheet(theme.list_qss(p))
        self.chat_view.setStyleSheet(theme.chat_view_qss(p))
        self._input_frame.setStyleSheet(theme.input_frame_qss(p))
        self._chat_hint.setStyleSheet(
            f"color:{p['sub']}; font-size:11px; border:none;")
        self.find_bar.setStyleSheet(theme.find_bar_qss(p))
        self.drop_zone.set_palette(p)
        self.editor.apply_theme(p)
        self._replay_chat_bubbles()
        self._refresh_syntax()      # 语法提示的底色也跟着主题走
        # 存的是"用户的选择"（可能是 system），不是解析出来的 light/dark ——
        # 否则点一次跟随系统就被改写成那天读到的实际配色，下次就再也不跟了
        st.setValue("ui_theme", mode)
        st.setValue("ui_font", size)

    def _watch_system_theme(self):
        """选了「跟随系统」时，系统配色变了要跟着变（不用重启）。

        Qt 6.6+ 会发 styleHints().colorSchemeChanged；老版本没有这个信号就退回
        "启动时读一次"（已在 _apply_theme 里读过），至少不会走错。
        """
        try:
            from PySide6.QtGui import QGuiApplication
            hints = QGuiApplication.styleHints()
            if hasattr(hints, "colorSchemeChanged"):
                hints.colorSchemeChanged.connect(self._on_system_theme_changed)
        except Exception:
            pass

    def _on_system_theme_changed(self, *_):
        if getattr(self, "_theme_mode", "light") != theme.SYSTEM:
            return                      # 用户明确选了某一套，系统变了我也不动
        want = "dark" if theme.system_prefers_dark() else "light"
        cur = getattr(self, "_palette", {}) or {}
        if cur.get("name") == want:
            return                      # 已经是这一套，省一次全量重绘
        self._apply_theme(theme.SYSTEM)
        self.statusBar().showMessage(
            f"系统切到了{'深色' if want == 'dark' else '浅色'}模式，界面已跟随", 4000)

    def _replay_chat_bubbles(self):
        """主题换了，已经画出来的气泡得按新配色重画一遍。

        只重画当前这场：归档在下拉框里的对话是在切回去时才渲染的
        （_load_chat_session 会重新 append），届时自然用上新配色。
        """
        bubbles = list(self.chat_bubbles)
        if not bubbles:
            return
        self.chat_view.clear()
        self.chat_bubbles = []
        for role, text in bubbles:
            self._append_chat(role, text)

    # ---------- 编辑器小工具：查找替换 / 跳转行 / 注释 / 语法标红

    def _refresh_syntax(self):
        """编辑器里的脚本语法自检：有错就把出错行标红 + 在编辑器下方说一句人话。

        这是"提醒"不是"拦截" —— 渲染前的静态检查（validator）仍然照跑，
        这里的价值是把"渲了 8 秒才告诉你第 12 行少个冒号"提前到敲字的当下。
        """
        code = self.editor.toPlainText()
        if not code.strip():
            self.editor.mark_error_line(None)
            self.lbl_syntax.hide()
            return
        try:
            compile(code, "<script>", "exec")
        except SyntaxError as e:
            self.editor.mark_error_line(e.lineno or 1)
            self.lbl_syntax.setText(
                f"⚠ 第 {e.lineno} 行语法错误：{e.msg}（脚本仍可渲染，"
                "但一定会失败 —— 建议先改好）")
            p = getattr(self, "_palette", None) or theme.palette("light")
            self.lbl_syntax.setStyleSheet(
                f"color:{p['warn_fg']}; background:{p['warn_bg']};"
                " border-radius:4px; padding:3px;")
            self.lbl_syntax.show()
            return
        except Exception:
            pass
        self.editor.mark_error_line(None)
        self.lbl_syntax.hide()

    def _show_find_bar(self, replace: bool = False):
        self.find_bar.show_find(replace)

    def _goto_line(self):
        from PySide6.QtWidgets import QInputDialog
        total = self.editor.document().blockCount()
        n, ok = QInputDialog.getInt(self, "跳转到行", f"行号（1 ~ {total}）：",
                                    1, 1, max(1, total), 1)
        if ok:
            self.editor.goto_line(n)

    def _toggle_comment(self):
        if QApplication.focusWidget() is self.editor:
            self.editor.toggle_comment()
        else:
            self.editor.setFocus()
            self.editor.toggle_comment()

    def _build_editor_shortcuts(self):
        pairs = [("Ctrl+F", lambda: self._show_find_bar(False)),
                 ("Ctrl+H", lambda: self._show_find_bar(True)),
                 ("Ctrl+L", self._goto_line),
                 ("Ctrl+/", self._toggle_comment)]
        for key, fn in pairs:
            sc = QShortcut(QKeySequence(key), self)
            sc.setContext(Qt.ShortcutContext.WindowShortcut)
            sc.activated.connect(fn)

    def _refresh_buttons(self):
        has_code = bool(self.editor.toPlainText().strip())
        self.btn_extract.setEnabled(bool(self.course_text.strip()))
        self.btn_batch.setEnabled(bool(self.knowledge_points))
        self._apply_media_enabled()
        # 生成脚本的唯一前提：对话里已确认过「呈现清单」（无课件模式也算）
        self.btn_generate.setEnabled(bool(self.chat_plan.strip()))
        self.btn_render.setEnabled(has_code)
        self.btn_qc.setEnabled(has_code)
        # 菜单里的运行动作与按钮状态保持一致
        self.act_extract.setEnabled(bool(self.course_text.strip()))
        self.act_generate.setEnabled(bool(self.chat_plan.strip()))
        self.act_render.setEnabled(has_code)
        self.act_render_hd_once.setEnabled(has_code)
        self.act_quickcheck.setEnabled(has_code)

    def _run_worker(self, worker, on_done, on_fail):
        self._worker = worker
        worker.log.connect(self._log)
        worker.done.connect(on_done)
        worker.fail.connect(on_fail)
        # 用 lambda 把 worker 自身捕获下来：跨线程信号里 sender() 会变成 None，
        # 而"在上一个任务的 done 回调里紧接着启动下一个任务"（先提炼标题再生成
        # 脚本就是这种链式调用）必须能分清到底是谁结束了。
        worker.finished.connect(lambda w=worker: self._on_worker_finished(w))
        self._set_busy(True)
        worker.start()   # 必须显式启动，否则 QThread 只是个摆设

    def _on_worker_finished(self, worker=None):
        worker = worker or self.sender()
        if worker is not None and worker is not self._worker:
            # 上一个 worker 迟到的 finished：当前跑的已经是下一个任务，
            # 此时清状态会把新任务误判为"已结束"，甚至把运行中的线程销毁掉。
            worker.deleteLater()
            return
        self._set_busy(False)
        self._worker = None
        if worker is not None:
            worker.deleteLater()

    # ---------- 槽：打开课件 / 提取

    def on_file_chosen(self, path: str):
        """投放区（点击或拖拽）的统一入口：先过格式与大小两道闸门，再解析。"""
        ext = os.path.splitext(path)[1].lower()
        if ext not in config.COURSE_EXTENSIONS:
            supported = " / ".join(ext2.lstrip(".") for ext2 in config.COURSE_EXTENSIONS)
            QMessageBox.warning(self, "不支持的格式",
                                f"「{ext.lstrip('.') or path}」不是支持的课件格式。\n"
                                f"支持：{supported}")
            return

        # 体积体检：看"文本成分"而非"总体重" —— 几百 MB 的 PPT 多为图片，照样能读
        verdict = parser.inspect_size(path)
        if not verdict.ok:
            QMessageBox.warning(self, "文件过大", verdict.message)
            return

        try:
            self.course_text = parser.parse_file(path)
        except Exception as e:
            QMessageBox.warning(self, "解析失败", str(e))
            return

        name = os.path.basename(path)
        real_chars = parser.meaningful_chars(self.course_text)
        if real_chars < 20:
            # 能力的边界要说在前面：没有文本层的文件读不出内容，别让用户误以为程序坏了
            self.course_text = ""
            self.lbl_file.setText("尚未打开课件")
            self._reset_results()
            self._refresh_buttons()
            QMessageBox.warning(
                self, "提取不到文字",
                f"「{name}」里几乎读不到任何文字。\n\n"
                "MathViz 只能读取文件中的文字层，下面这些情况是读不到的：\n"
                "  · 扫描件、拍照生成的 PDF（字是画在图上的）\n"
                "  · 整页由图片构成的 PPT / Word\n\n"
                "请先用 OCR 工具转换成带文字层的 PDF / Word，"
                "或改用能选中文字的源文件再导入。")
            return

        self.lbl_file.setText(f"📄 {name}（{real_chars} 字符）")
        if verdict.level == "notice":
            self._log(f"[课件] ⚠ {verdict.message.replace(chr(10), ' ')}")
        self._reset_results()   # 换课件必须清空上一份的残留，否则会看到"张冠李戴"的旧知识点
        self._append_chat("system", f"已加载课件「{name}」，对话将基于它进行")
        self._refresh_buttons()   # course_text 就绪 → 启用「提取知识点」
        self._log(f"[课件] 已解析 {name}，{len(self.course_text)} 字符")
        if len(self.course_text) > config.MAX_COURSETEXT_CHARS:
            self._log(f"[课件] ⚠ 文本超出 AI 上下文预算，调用时将截断至 "
                      f"{config.MAX_COURSETEXT_CHARS} 字符（建议拆分课件）")

    def _current_domain(self) -> str:
        """当前选中的学科 key（未来新增学科时无需改动本方法）。"""
        return self.combo_domain.currentData() or domains.DEFAULT_DOMAIN

    # ---------- 缓存：同一知识点不再重复烧 token

    @staticmethod
    def _cache_lookup(domain: str, kp: dict) -> cache.CacheEntry | None:
        """查某个知识点有没有旧稿。"""
        return cache.get(domain, kp.get("title", ""), kp.get("description", ""))

    def _open_settings(self):
        """「选项」弹窗：读写设置并即时生效。"""
        dlg = SettingsDialog(self)
        dlg.load()
        if dlg.exec():
            dlg.apply()
            self._log("[选项] 设置已更新")

    def _toggle_cache(self, checked: bool):
        cache.set_enabled(checked)
        # 显式同步勾选：从菜单触发时 Qt 会自己改，从代码切换时不会
        self.act_cache.setChecked(cache.is_enabled())
        state = "开启" if checked else "关闭"
        self._log(f"[缓存] 已{state}。开启时，双击做过的知识点会直接复用上次的成果。")
        self._refresh_point_marks()   # 列表上的 💾 标记要跟着出现/消失
        self._refresh_history()       # 历史成果列表同样跟着开关走

    def _refresh_point_marks(self):
        """刷新知识点列表里的缓存标记，并显示命中数量。"""
        domain = self._current_domain()
        hits = 0
        for i, kp in enumerate(self.knowledge_points):
            item = self.point_list.item(i)
            if item is None:
                continue
            entry = None
            if cache.is_enabled():
                # touch=False：刷新界面不该把命中计数刷上去
                entry = cache.get(domain, kp.get("title", ""),
                                  kp.get("description", ""), touch=False)
            base = kp.get("title", "")
            level = f"｜{kp['level']}" if kp.get("level") else ""
            if entry:
                hits += 1
                item.setText(f"💾 {base}{level}")
                item.setToolTip(f"已缓存（{entry.summary()}）\n双击直接复用，不调用 AI")
            else:
                item.setText(f"{base}{level}")
                item.setToolTip("双击或点击右侧 ➜ 送入对话确认")
        if self.knowledge_points:
            self._log(f"[缓存] 本课件 {len(self.knowledge_points)} 个知识点，"
                      f"其中 {hits} 个可直接复用")

    def _apply_cached_entry(self, entry: cache.CacheEntry, kp: dict):
        """命中缓存：把上次的成果直接摆上来，一次 API 都不调用。"""
        code = entry.load_code()
        if not code.strip():
            self._log("[缓存] 条目内容为空，改为正常生成")
            return False
        # 缓存键只看学科 + 标题，描述不参与 —— 换了讲法也照样命中，
        # 不说清楚他会以为新描述生效了（拿到的其实是旧动画）。
        want = (kp.get("description") or "").strip()
        have = (entry.description or "").strip()
        if want and have and want != have:
            self._log("[缓存] 按标题命中，描述不参与比对：这次的描述与旧稿不同。"
                      "想按新讲法重做，请先在「选项」里关掉缓存，或把标题改一下")
        self.editor.setPlainText(code)
        # Scene 名以缓存脚本里真正的类名为准（比记住的更可靠）
        names = renderer._scene_class_names(code)
        self.current_scene_name = names[0] if names else entry.scene_name
        self.current_point_title = entry.title or kp.get("title", "")
        self.lbl_scene.setText(f"Scene: {self.current_scene_name}（缓存复用）")
        self.chat_plan = entry.load_plan()
        self._append_chat("system",
                          f"命中缓存：直接复用 {entry.created_text} 的成果，本次不调用 AI")
        if self.chat_plan:
            # 把当初确认的清单摆出来，让用户知道自己复用的是什么
            self._append_chat("assistant", self.chat_plan)
        if entry.has_video():
            self._load_video(entry.video)
            self.tabs.setCurrentIndex(0)
            self._log(f"[缓存] 已载入旧脚本与成片（{entry.summary()}）")
        else:
            self._log(f"[缓存] 已载入旧脚本（{entry.summary()}），可直接渲染")
        self._refresh_buttons()
        self._refresh_versions()   # 切到这个知识点自己的版本时间线
        return True

    # ---------- 历史成果：跨会话直接调用以前做过的知识点

    # ---------- 播放器模式（朋友建议的"大屏视频 + 知识点目录"形态）

    def _restore_layout_mode(self):
        """启动布局：一律工作台。

        播放器模式被设计成"看片时的临时状态"，不跨会话保留 —— 上次渲染完直接
        关掉程序，下次打开仍从工作台开始（一开程序就怼一脸大屏视频并不友好，
        也顺带杜绝了"启动即恢复播放器模式"这类时序问题）。存档里的旧值在这里
        清掉；将来若想改回"记住上次布局"，把这段换回读值再 setChecked 即可。
        """
        st = QSettings("MathViz", "MathViz")
        if st.contains("player_mode"):
            st.remove("player_mode")
        self.act_player_mode.setChecked(False)   # 已经是 False 时不会触发 toggled

    def _toggle_player_mode(self, on: bool):
        """纯显隐切换：不 reparent 任何控件，随时能原样切回工作台。"""
        # 存档只作为"本次会话的布局记录"，启动时按用户需求一律回到工作台
        # （见 _restore_layout_mode），这里保留写入是为了方便将来改回持久化。
        QSettings("MathViz", "MathViz").setValue("player_mode", bool(on))
        if on:
            self._wb_sizes = self.root_splitter.sizes()
            self._rs_sizes = self.right_splitter.sizes()
            self._left_panel.hide()
            self._middle_panel.hide()
            self._editor_panel.hide()
            try:
                self.tabs.setTabVisible(1, False)   # 藏日志页，只留预览
            except Exception:
                pass   # 老版 Qt 没有该接口，日志页留着也不碍事
            self.player_bar.show()
            self.tabs.setCurrentIndex(0)
            self._refresh_player_nav()
            self.btn_expand.hide()      # 已是大屏；双击画面即可退出
        else:
            self.player_bar.hide()
            self._left_panel.show()
            self._middle_panel.show()
            self._editor_panel.show()
            try:
                self.tabs.setTabVisible(1, True)
            except Exception:
                pass
            # 恢复进入前的分割比例
            if getattr(self, "_wb_sizes", None):
                self.root_splitter.setSizes(self._wb_sizes)
            if getattr(self, "_rs_sizes", None):
                self.right_splitter.setSizes(self._rs_sizes)
            self.btn_expand.show()
            self._place_expand_btn()
        self._log("[布局] " + ("已切换到播放器模式（视频大屏 + 知识点目录）"
                              if on else "已切回工作台布局"))

    def _exit_player_mode(self):
        self.act_player_mode.setChecked(False)   # 触发 toggled → 切回

    def _auto_player_mode(self):
        """渲染成功后自动进播放器模式看片（「选项」里可关闭）。

        已经在大屏里的话就只刷新目录条，避免重复切换；任何时候都能点
        「◀ 返回工作台」或用菜单取消勾选回到工作台。
        """
        if self.act_player_mode.isChecked():
            self._refresh_player_nav()
        elif QSettings("MathViz", "MathViz").value(
                "auto_player_mode", True, type=bool):
            self.act_player_mode.setChecked(True)   # 触发 toggled → 进播放器模式

    def _refresh_player_nav(self):
        """目录条：全部（= 当前视频）+ 各个有成片的知识点按钮。"""
        while self.player_nav_layout.count():
            it = self.player_nav_layout.takeAt(0)
            w = it.widget()
            if w is not None:
                w.deleteLater()
        # 「全部」：播放当前视频（朋友的原话：选全部就放你现在的视频）
        # getattr 防御：启动恢复时 _build_media 可能还没跑，current_video 尚未出生
        btn_all = QPushButton("全部")
        btn_all.setEnabled(bool(getattr(self, "current_video", None)))
        btn_all.clicked.connect(self._replay)
        self.player_nav_layout.addWidget(btn_all)
        # 各知识点：从缓存里挑有成片的条目，点一下直接播
        shown = 0
        for entry in cache.all_entries():
            if not entry.has_video() or not entry.video:
                continue
            if not os.path.exists(str(entry.video)):
                continue
            b = QPushButton(entry.title or "未命名")
            b.setToolTip(f"播放「{entry.title}」的成片（{entry.created_text} 制作）")
            b.clicked.connect(lambda _=False, v=str(entry.video): self._load_video(v))
            self.player_nav_layout.addWidget(b)
            shown += 1
            if shown >= 12:
                self.player_nav_layout.addWidget(
                    QLabel("…更多请在工作台的历史成果里找"))
                break
        if shown == 0:
            self.player_nav_layout.addWidget(
                QLabel("还没有成片 —— 回工作台渲染一个吧"))

    # ---------- 脚本版本快照（改坏了能退回去）

    def _versions_key(self) -> str:
        """版本时间线的 key：按知识点标题划分（退化到 Scene 名）。"""
        return versions.make_key(self.current_point_title,
                                 self.current_scene_name)

    def _snapshot(self, label: str, code: str = "") -> None:
        """存一版并刷新下拉框。失败静默（版本功能不该拖垮主流程）。"""
        code = code if code else self.editor.toPlainText()
        if not code.strip():
            return
        versions.add(self._versions_key(), code, label, self.current_scene_name)
        self._refresh_versions()

    def _refresh_versions(self, select_idx: int | None = None):
        vs = versions.list_versions(self._versions_key())
        self.cmb_version.blockSignals(True)
        self.cmb_version.clear()
        self.cmb_version.addItem("当前编辑器", None)
        idx_to_select = 0
        for v in vs:
            self.cmb_version.addItem(v.display(), v.idx)
            if select_idx is not None and v.idx == select_idx:
                idx_to_select = self.cmb_version.count() - 1
        self.cmb_version.blockSignals(False)
        self.cmb_version.setCurrentIndex(idx_to_select)
        self._on_version_selected()
        self.btn_ver_save.setEnabled(bool(self.editor.toPlainText().strip()))

    def _selected_version(self) -> versions.Version | None:
        idx = self.cmb_version.currentData()
        if not idx:
            return None
        return versions.get_version(self._versions_key(), idx)

    def _on_version_selected(self):
        v = self._selected_version()
        self.btn_ver_revert.setEnabled(v is not None)
        self.btn_ver_diff.setEnabled(v is not None)

    def _save_version(self):
        cur = self.editor.toPlainText()
        if not cur.strip():
            QMessageBox.information(self, "提示", "编辑器里没有内容")
            return
        v = versions.add(self._versions_key(), cur, versions.LBL_MANUAL,
                         self.current_scene_name)
        self._refresh_versions(v.idx if v else None)
        self._log(f"[版本] 已存档一份（{versions.stat_text(self._versions_key())}）")

    def _revert_version(self):
        v = self._selected_version()
        if not v:
            return
        old = v.code
        if not old.strip():
            QMessageBox.warning(self, "版本不可用", "那一版的内容读不出来（文件已损坏）")
            return
        cur = self.editor.toPlainText()
        # 先把"退回之前"的内容留一份，这一步很关键：
        # 否则用户改了半天又点了退回，那些改动就永久消失了。
        if cur.strip() and cur.strip() != old.strip():
            versions.add(self._versions_key(), cur, "退回前自动存档",
                         self.current_scene_name)
        self.editor.setPlainText(old)
        versions.add(self._versions_key(), old,
                     f"{versions.LBL_REVERT}至 v{v.idx}", self.current_scene_name)
        self._refresh_versions()
        self._log(f"[版本] 已退回 v{v.idx}（{v.time_text()} · {v.label}）；"
                  f"退回前的改动已自动存档")
        self._refresh_buttons()

    def _diff_version(self):
        v = self._selected_version()
        if not v:
            return
        text = versions.diff_text(v.code, self.editor.toPlainText(),
                                  old_name=f"v{v.idx}（{v.label}）",
                                  new_name="编辑器当前内容")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"差异对比：v{v.idx} ↔ 当前内容")
        dlg.resize(720, 480)
        lay = QVBoxLayout(dlg)
        tip = QLabel("红色 − 是旧版有、现在没有的；绿色 + 是现在新增的。")
        tip.setStyleSheet("color:#6b7280; font-size:12px;")
        lay.addWidget(tip)
        view = QPlainTextEdit()
        view.setReadOnly(True)
        view.setPlainText(text)
        from PySide6.QtGui import QFont
        f = QFont("Consolas", 10)
        f.setStyleHint(QFont.StyleHint.Monospace)
        view.setFont(f)
        lay.addWidget(view, 1)
        row = QHBoxLayout()
        btn_copy = QPushButton("复制差异")
        btn_copy.clicked.connect(
            lambda: QApplication.clipboard().setText(text))
        btn_close = QPushButton("关闭")
        btn_close.clicked.connect(dlg.accept)
        row.addStretch(1)
        row.addWidget(btn_copy)
        row.addWidget(btn_close)
        lay.addLayout(row)
        dlg.exec()

    def _refresh_history(self):
        """把缓存里所有条目列出来（不受"本次有没有开课件"影响）。

        缓存目录就在项目里（cache/），程序退出不会清；之前"看不见"是因为
        没有入口 —— 只有重新提取同一份课件、且 AI 这次给的标题与上次一字不差
        才会显示 💾 标记，自然像是"缓存没了"。
        """
        if not hasattr(self, "history_list"):
            return
        self.history_list.clear()
        self._history_entries = cache.all_entries() if cache.is_enabled() else []
        for e in self._history_entries:
            mark = "🎞 " if e.has_video() else "📄 "
            item = QListWidgetItem(f"{mark}{e.title}")
            tip = (f"{e.summary()}\n学科：{e.domain}"
                   + ("\n双击载入脚本与成片" if e.has_video() else "\n双击载入脚本"))
            item.setToolTip(tip)
            self.history_list.addItem(item)
        n = len(self._history_entries)
        if n:
            n_vid = sum(1 for e in self._history_entries if e.has_video())
            self._log(f"[历史] 缓存共 {n} 个知识点（{n_vid} 个带成片），"
                      "双击可直接载入，不调用 AI")
        elif not cache.is_enabled():
            self._log("[历史] 缓存已关闭，历史列表为空（选项 → 启用生成缓存）")

    def _on_history_activated(self, item):
        row = self.history_list.row(item)
        entries = getattr(self, "_history_entries", [])
        if not (0 <= row < len(entries)):
            return
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在忙", "有任务正在运行，等它结束后再载入。")
            return
        entry = entries[row]
        if self._apply_cached_entry(entry, {"title": entry.title,
                                            "description": entry.description}):
            self.point_list.clearSelection()
            self._log(f"[历史] 已载入「{entry.title}」（{entry.summary()}）")

    def _history_menu(self, pos):
        item = self.history_list.itemAt(pos)
        if item is None:
            return
        row = self.history_list.row(item)
        entries = getattr(self, "_history_entries", [])
        if not (0 <= row < len(entries)):
            return
        entry = entries[row]
        menu = QMenu(self)
        act_load = menu.addAction("载入这条成果")
        menu.addSeparator()
        act_del = menu.addAction("删除这条缓存")
        chosen = menu.exec(self.history_list.viewport().mapToGlobal(pos))
        if chosen == act_load:
            self._on_history_activated(item)
        elif chosen == act_del:
            ans = QMessageBox.question(
                self, "删除缓存",
                f"删除「{entry.title}」这条缓存？\n"
                "（只是不再复用，media/ 里已渲染的成片不会被删）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans == QMessageBox.StandardButton.Yes:
                cache.delete(entry.key)
                self._refresh_history()
                self._log(f"[缓存] 已删除「{entry.title}」")

    def _show_cache_stats(self):
        st = cache.stats()
        entries = cache.all_entries()
        lines = [f"缓存条目：{st['count']} 条",
                 f"累计复用：{st['hits']} 次",
                 f"带成片：{st['with_video']} 条",
                 f"脚本总量：{st['chars']} 字符",
                 f"位置：{cache.CACHE_DIR}",
                 ""]
        for e in entries[:12]:
            lines.append(f"· {e.title}（{e.summary()}）")
        if len(entries) > 12:
            lines.append(f"…… 其余 {len(entries) - 12} 条")
        QMessageBox.information(self, "缓存统计", "\n".join(lines))

    def _clear_cache(self):
        if cache.stats()["count"] == 0:
            QMessageBox.information(self, "缓存", "当前没有缓存内容。")
            return
        ans = QMessageBox.question(
            self, "清除缓存",
            "将删除所有已缓存知识点（脚本与索引）。\n"
            "已渲染并归档在 media/ 里的成片不会被删除。\n\n确定清除吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if ans != QMessageBox.StandardButton.Yes:
            return
        n = cache.clear_all()
        self._refresh_point_marks()
        self._refresh_history()
        self._log(f"[缓存] 已清除 {n} 条缓存")

    def _reset_results(self):
        """清空知识点列表、编辑器、对话与当前场景名（换课件时用）。"""
        self.knowledge_points = []
        self._kp_hover_item = None
        self._kp_send_btn.hide()
        self.point_list.clear()
        self.editor.clear()
        self.current_scene_name = ""
        self.current_point_title = ""
        self.lbl_scene.setText("")
        # 换课件等于换一批知识点：上一场的对话先收起来，别和新课件的内容混着聊
        self._archive_current_chat()
        self.chat_topic = ""
        self._reset_chat()
        self._refresh_chat_combo()

    # ---------- 槽：清空（重置到初始状态）

    def _has_work(self) -> bool:
        """当前是否已经"有内容"——决定是否真的需要清空、是否需要二次确认。"""
        return any((
            bool(self.course_text.strip()),
            bool(self.knowledge_points),
            bool(self.editor.toPlainText().strip()),
            bool(self.chat_history),
            bool(self.chat_input.toPlainText().strip()),
            self.current_video is not None,
            bool(self.log_view.toPlainText().strip()),
        ))

    def _reset_video(self):
        """把预览区恢复成"尚未渲染视频"的初始态。"""
        try:
            self.player.stop()
            self.player.setSource(QUrl())   # 断开源，否则会继续占着文件
        except Exception:
            pass
        self.current_video = None
        self._external_opened = False
        self.lbl_video.setText("尚未渲染视频")
        for b in (self.btn_play, self.btn_replay):
            b.setEnabled(False)
        self._apply_media_enabled()
        self.btn_play.setText("▶ 播放")
        self.slider.setEnabled(False)
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.lbl_time.setText("00:00 / 00:00")

    def on_clear(self):
        """重置整个工作区。已归档到 media/ 的成片不删——那是用户的产物。"""
        if self._worker is not None and self._worker.isRunning():
            QMessageBox.information(self, "正在忙",
                                    "有任务正在运行，等它结束后再清空。")
            return
        if not self._has_work():
            self.statusBar().showMessage("已经是初始状态了", 3000)
            return

        # 「选项」里可以关掉这个二次确认（关掉后点清空立即执行）
        if QSettings("MathViz", "MathViz").value("clear_confirm", True, type=bool):
            ans = QMessageBox.question(
                self, "确认清空",
                "将重置整个工作区，回到刚打开时的状态：\n"
                "  · 已加载的课件\n"
                "  · 提取出的知识点\n"
                "  · 中间的对话与呈现清单\n"
                "  · 编辑器里的脚本\n"
                "  · 预览区与运行日志\n\n"
                "（已渲染并归档在 media/ 里的成片不会被删除）\n\n"
                "确定要清空吗？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if ans != QMessageBox.StandardButton.Yes:
                return

        self.course_text = ""
        self.knowledge_points = []
        self._kp_hover_item = None
        self._kp_send_btn.hide()
        self.chk_revise.setChecked(False)   # 代码修改模式也回到初始态
        self.point_list.clear()
        self.lbl_file.setText("尚未打开课件")
        self.editor.clear()
        self.current_scene_name = ""
        self.current_point_title = ""
        self.lbl_scene.setText("")
        self._kp_counter = 0
        self.chat_input.clear()
        self.chat_sessions = []     # 归档的对话也一并清掉（"回到刚打开时"）
        self.chat_topic = ""
        self._reset_chat()          # 回到开场白
        self._refresh_chat_combo()
        self._reset_video()
        self.log_view.clear()
        self.tabs.setCurrentIndex(0)
        self._refresh_buttons()
        self._refresh_versions()    # 版本下拉框跟着复位
        self.statusBar().showMessage("已清空，回到初始状态", 5000)

    def on_extract(self):
        if not self.course_text:
            QMessageBox.information(self, "提示", "请先打开课件")
            return

        def done(points):
            self.knowledge_points = points
            self._kp_hover_item = None
            self._kp_send_btn.hide()
            self.point_list.clear()
            for p in points:
                level = f"｜{p['level']}" if p.get("level") else ""
                QListWidgetItem(f"{p['title']}{level}", self.point_list)
            self.tabs.setCurrentIndex(0)
            self._refresh_point_marks()   # 标出哪些知识点已有旧稿可复用
            self._log("[知识点] 提取完成，双击条目送入对话，确认后生成脚本")

        def fail(err):
            # 提取不到数学内容不是"出错"，是这份文档不合适 —— 用普通提示而非警告，并清空列表
            self._reset_results()
            # 注意：异常经 Qt 信号传递后已是字符串，这里按内容判断
            if "没有从中提取到" in str(err):
                self._log(f"[知识点] {err}")
                QMessageBox.information(self, "没有找到数学知识点", str(err))
            else:
                QMessageBox.warning(self, "提取失败", str(err))

        self._run_worker(ExtractWorker(self.course_text, self._current_domain()),
                         done, fail)

    # ---------- 槽：对话式内容确认

    _GREETING = (
        "把课件拖进左侧，我会基于它给出「呈现清单」；\n"
        "没有课件也没关系，直接告诉我你想学什么。\n"
        "可以随时让我增删知识点，确认后点【生成脚本】。")

    _FORMULA_TPL = ("<code style='background:#eef3fa; color:#15457f;"
                    " font-family:\"Consolas\",\"Cambria Math\",monospace;"
                    " padding:1px 4px; border-radius:3px;'>\\1</code>")
    # 气泡与公式块的颜色随主题走（类属性是浅色默认值，建窗口后由 _apply_theme 覆盖）
    _bc = theme.bubble_colors(theme.LIGHT)

    def _append_chat(self, role: str, text: str):
        """往对话视图里补一个气泡。role: user / assistant / system"""
        self.chat_bubbles.append((role, text))
        esc = html_mod.escape(text).replace("\n", "<br>")
        # $…$ 里的公式用等宽 + 淡蓝底标出来，和周围中文一眼分得开
        tpl = ("<code style='background:%s; color:%s;"
               " font-family:\"Consolas\",\"Cambria Math\",monospace;"
               " padding:1px 4px; border-radius:3px;'>\\1</code>"
               % (self._bc["formula_bg"], self._bc["formula_fg"]))
        esc = re.sub(r"\$([^$\n]{1,200})\$", tpl, esc)
        if role == "user":
            bubble = (f"<table width='100%' cellspacing='0' cellpadding='0'>"
                      f"<tr><td width='18%'></td><td align='right'>"
                      f"<span style='background-color:{self._bc['user']}; border-radius:6px;'>"
                      f"&nbsp;{esc}&nbsp;</span></td></tr></table>")
        elif role == "system":
            bubble = (f"<div align='center'><i><span style='color:{self._bc['system']};'>"
                      f"— {esc} —</span></i></div>")
        else:
            bubble = (f"<table width='100%' cellspacing='0' cellpadding='0'>"
                      f"<tr><td align='left'>"
                      f"<span style='background-color:{self._bc['bot']}; border-radius:6px;'>"
                      f"&nbsp;{esc}&nbsp;</span></td><td width='8%'></td></tr></table>")
        self.chat_view.append(bubble + "<br>")
        sb = self.chat_view.verticalScrollBar()
        sb.setValue(sb.maximum())

    def _reset_chat(self, greeting: bool = True):
        """清空对话。换课件 / 重开一轮策划时调用。"""
        self.chat_history = []
        self.chat_plan = ""
        self.chat_bubbles = []
        self.chat_view.clear()
        if greeting:
            self._append_chat("system", self._GREETING)

    # ---------- 对话分页：一个知识点一场对话

    def _chat_has_content(self) -> bool:
        """当前对话有没有"实质内容"（开场白这类系统提示不算）。"""
        return any(r in ("user", "assistant") for r, _ in self.chat_bubbles)

    def _archive_current_chat(self) -> bool:
        """把当前对话收进会话列表。返回是否真的归档了（没内容就不占位置）。"""
        if not self._chat_has_content():
            return False
        title = self.chat_topic or "自由对话"
        # 同名会话只保留最新那场（反复点同一个知识点不该堆出一串）
        self.chat_sessions = [s for s in self.chat_sessions if s["title"] != title]
        self.chat_sessions.append({
            "title": title,
            "bubbles": list(self.chat_bubbles),
            "history": list(self.chat_history),
            "plan": self.chat_plan,
        })
        return True

    def _refresh_chat_combo(self):
        self.combo_chat.blockSignals(True)
        self.combo_chat.clear()
        self.combo_chat.addItem(f"当前：{self.chat_topic or '自由对话'}")
        for s in self.chat_sessions:
            rounds = sum(1 for m in s.get("history", []) if m.get("role") == "user")
            self.combo_chat.addItem(f"{s['title']}（{rounds} 轮）")
        self.combo_chat.setCurrentIndex(0)
        self.combo_chat.blockSignals(False)

    def _on_chat_session_switch(self, idx: int):
        if idx <= 0:
            return    # 第 0 项就是"当前"，切它没意义
        target = self.chat_sessions.pop(idx - 1)   # 先取走，免得归档时索引错位
        self._archive_current_chat()
        self._load_chat_session(target)
        self._refresh_chat_combo()

    def _load_chat_session(self, s: dict):
        self.chat_topic = s.get("title", "")
        self.chat_history = list(s.get("history", []))
        self.chat_plan = s.get("plan", "")
        self.chat_view.clear()
        self.chat_bubbles = []
        self._append_chat("system", f"切回「{self.chat_topic}」的对话")
        for role, text in s.get("bubbles", []):
            self._append_chat(role, text)
        self._log(f"[对话] 已切回「{self.chat_topic}」")
        self._refresh_buttons()

    def _start_new_chat(self):
        """手动开一场新对话：当前的收进下拉框，对话区清空。"""
        archived = self._archive_current_chat()
        self.chat_topic = ""
        self._reset_chat(greeting=True)
        if archived:
            self._append_chat(
                "system", "上一场对话已收进上方「对话」下拉框，可随时切回")
        self._refresh_chat_combo()
        self._log("[对话] 已开一场新对话（旧的仍可从下拉框切回）")

    def _ensure_chat_topic(self, topic: str):
        """换知识点就换一场对话：旧的自动收起，界面立刻干净。

        这样做是因为：AI 的策划是"看着整段对话历史"来的，留着上一个知识点的
        讨论再聊新的，它会把两件事掺在一起。
        """
        if self.chat_topic == topic:
            return
        archived = False
        if self.chat_topic or self._chat_has_content():
            archived = self._archive_current_chat()
            self.chat_history = []
            self.chat_plan = ""
            self.chat_bubbles = []
            self.chat_view.clear()
        self.chat_topic = topic
        self._append_chat(
            "system",
            f"新知识点：{topic}"
            + ("（上一场对话已收进上方「对话」下拉框）" if archived else ""))
        self._refresh_chat_combo()
        self._refresh_buttons()

    # ---------- 公式输入

    def _open_formula_editor(self):
        """调出 LaTeX 公式编辑器，确认后以 $…$ 插入输入框光标处。"""
        dlg = FormulaDialog(self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        tex = dlg.latex()
        if not tex:
            return
        snippet = tex if (tex.startswith("$") and tex.endswith("$")) else f"${tex}$"
        cur = self.chat_input.textCursor()
        cur.insertText((" " if cur.position() else "") + snippet + " ")
        self.chat_input.setFocus()
        self._log(f"[公式] 已插入 {snippet[:60]}")

    def on_send(self):
        text = self.chat_input.toPlainText().strip()
        if not text:
            return
        if not config.get_api_key():
            QMessageBox.warning(self, "未配置 Key",
                                "对话需要 DeepSeek API Key，请先配置（见帮助/README）。")
            return
        self.chat_input.clear()
        if self.chk_revise.isChecked():
            self._revise_code(text)
        else:
            self._send_message(text)

    def _revise_code(self, text: str):
        """代码修改模式：当前脚本 + 用户要求 → AI 直接改代码（呈现清单不变）。"""
        code = self.editor.toPlainText().strip()
        if not code:
            QMessageBox.information(
                self, "还没有可修改的脚本",
                "代码修改模式需要先有脚本：请先生成（或粘贴）一段 Manim 脚本，"
                "再描述要改什么。")
            return
        scene = (self.current_scene_name
                 or (renderer._scene_class_names(code) or ["KPCustom"])[0])
        self._append_chat("user", "🛠 [改代码] " + text)
        self._log(f"[代码修改] 提交要求：{text[:80]}")

        def done(new_code):
            self.editor.setPlainText(new_code)
            self.tabs.setCurrentIndex(0)
            self._append_chat(
                "system",
                "✅ 已按你的要求修改脚本（呈现清单保持不变）。"
                "点「渲染预览」看效果；不满意可继续追加要求。")
            self._log("[代码修改] 脚本已更新，静态检查通过")
            self._snapshot(versions.LBL_REVISE, new_code)
            self._refresh_buttons()

        def fail(err):
            self._append_chat("system", f"本次修改失败：{err}")
            self._log(f"[代码修改] 失败：{err}")

        self._run_worker(
            ReviseWorker(code, text, scene, self._current_domain()),
            done, fail)

    def _send_message(self, text: str, already_shown: bool = False):
        """把一条用户消息送进策划对话（输入框来源、双击知识点、或重新生成）。

        already_shown=True 用于"重新生成"：那时的提问气泡还在界面上、
        也还在 chat_history 里，重复追加会让它出现两次，AI 也会看到两遍同样的问题。
        """
        if not already_shown:
            self._append_chat("user", text)
            self.chat_history.append({"role": "user", "content": text})

        def done(reply):
            self.chat_plan = reply
            self.chat_history.append({"role": "assistant", "content": reply})
            self._append_chat("assistant", reply)
            self._log("[策划] 已更新呈现清单，确认后可生成脚本")
            self._refresh_buttons()

        def fail(err):
            self._append_chat("system", f"本次对话失败：{err}")
            self._log(f"[策划] 失败：{err}")

        self._run_worker(
            ChatWorker(list(self.chat_history), self.course_text,
                       self._current_domain()),
            done, fail)

    def on_point_activated(self, item):
        """双击知识点：有旧稿就直接复用，否则送入对话让 AI 先出清单。"""
        kp = self._selected_point()
        if not kp:
            return
        self._ensure_chat_topic(kp.get("title", "知识点"))   # 换知识点 = 换一场对话
        entry = cache.get(self._current_domain(),
                          kp.get("title", ""), kp.get("description", ""))
        if entry and self._apply_cached_entry(entry, kp):
            return    # 命中：一次 API 都没调用
        msg = f"我想重点可视化这个知识点：《{kp['title']}》"
        if kp.get("description"):
            msg += f"（{kp['description']}）"
        self._send_message(msg)

    # ---------- 槽：生成脚本

    def _selected_point(self) -> dict | None:
        row = self.point_list.currentRow()
        return self.knowledge_points[row] if 0 <= row < len(self.knowledge_points) else None

    def on_generate(self):
        """按对话确认的呈现清单生成脚本。

        - 左侧选中了知识点 → 直接以它为标题；
        - 纯对话模式（无课件 / 未选知识点）→ 先让 AI 把用户的描述提炼成一个
          简短知识点名，脚本与成片都用它命名（缓存也因此更容易命中）。
        """
        kp = self._selected_point()
        plan = self.chat_plan.strip()
        if not plan and not kp:
            QMessageBox.information(
                self, "提示",
                "请先在中间的对话窗口确认内容：\n"
                "直接输入想学的知识点，或双击左侧知识点让它先出一份「呈现清单」。")
            return

        if kp:
            self._start_generate(kp["title"], kp.get("description") or plan,
                                 kp.get("level", ""))
            return

        user_text = "\n".join(m["content"] for m in self.chat_history
                              if m["role"] == "user").strip()
        if not user_text:
            self._start_generate("自定义动画", plan, "")
            return

        def on_title(title):
            self._log(f"[标题] 你的描述被提炼为「{title}」，脚本与成片都用它命名")
            self._append_chat("system", f"本次知识点标题：{title}")
            self._start_generate(title, plan, "")

        def on_fail(err):
            # 提炼标题失败不该挡住生成：退回用原话首行
            first = user_text.splitlines()[0].strip("《》「」【】 ")
            title = first[:20] or "自定义动画"
            self._log(f"[标题] 提炼失败（{err}），退回用「{title}」命名")
            self._start_generate(title, plan, "")

        self._run_worker(TopicWorker(user_text, self._current_domain()),
                         on_title, on_fail)

    def _start_generate(self, title: str, description: str, level: str):
        """标题定下来之后真正启动生成。"""
        self.current_point_title = title

        self._kp_counter += 1
        scene_name = f"KP{time.strftime('%m%d_%H%M%S')}_{self._kp_counter}"
        self.current_scene_name = scene_name
        self.lbl_scene.setText(f"Scene: {scene_name}")

        domain = self._current_domain()
        plan_now = self.chat_plan

        def done(code, name):
            self.editor.setPlainText(code)
            self.tabs.setCurrentIndex(0)
            self._log(f"[脚本] 已写入编辑器（{len(code)} 字符），可手动微调后渲染")
            self._snapshot(versions.LBL_GENERATE, code)
            cache.save(domain, title, description, code, scene_name=name,
                       plan=plan_now, level=level)
            self._refresh_history()   # 刚生成的这条立刻出现在历史列表里
            self._refresh_buttons()

        def fail(err):
            QMessageBox.warning(self, "生成失败", err)

        self._run_worker(
            GenerateWorker(title, description, level, self.course_text,
                           scene_name, domain, plan=self.chat_plan),
            done, fail)

    # ---------- 槽：渲染

    def _current_layout(self) -> str:
        return self.combo_layout.currentData() or "16:9"

    def _save_layout_choice(self):
        QSettings("MathViz", "MathViz").setValue("render_layout",
                                                 self._current_layout())

    def on_render(self, quality: str):
        code = self.editor.toPlainText().strip()
        if not code:
            QMessageBox.information(self, "提示", "编辑器里还没有脚本")
            return
        if not tex_ready(self):   # 没有 LaTeX 就别白跑一趟
            return
        if not self.current_scene_name:
            self.current_scene_name = f"KP{time.strftime('%m%d_%H%M%S')}"
            self.lbl_scene.setText(f"Scene: {self.current_scene_name}")
        config.ensure_dirs()

        title_now = self.current_point_title
        domain_now = self._current_domain()

        def done(ok, mp4, msg):
            self.render_bar.hide()
            self.render_bar.setValue(0)
            if ok and mp4:
                self._log(f"[完成] 成片已归档：{mp4}")
                self._load_video(mp4)
                self.tabs.setCurrentIndex(0)
                # 渲染跑通的那版脚本才是"定稿"（期间可能自动修过），回写到缓存
                if title_now:
                    cache.record_video(domain_now, title_now, "", str(mp4),
                                       code=self.editor.toPlainText())
                    self._refresh_history()   # 历史列表上出现 🎞 标记
                if quality == "high":
                    self._log("[命名] 高清成片已加 [HD] 前缀，与 480p 预览区分")
                # 渲染成功的这版就是"跑通过的一版"，值得留个快照
                self._snapshot(versions.LBL_RENDERED)
                # 渲染出来了就自动放大屏看（目录条此时已含刚出炉的这支）
                self._auto_player_mode()
            else:
                self._show_render_failure(msg)

        rng = self._current_anim_range()
        if rng:
            self._log(f"[渲染] 只渲染第 {rng[0]}~{rng[1]} 段（共 {renderer.count_plays(code)} 段）")
        w = RenderWorker(code, self.current_scene_name, quality,
                         self._current_domain(),
                         archive_stem=self.current_point_title or None,
                         layout=self._current_layout(), anim_range=rng)
        w.progress.connect(self._on_render_progress)
        self.render_bar.setFormat("渲染 %p%")
        self._run_worker(w, done,
                         lambda e: (self.render_bar.hide(),
                                    self._show_render_failure(e, title="渲染错误")))
        self.tabs.setCurrentIndex(1)

    # ---------- 槽：批量队列

    def on_batch(self):
        if not self.knowledge_points:
            QMessageBox.information(
                self, "还没有知识点",
                "先打开课件并点【提取知识点】，或者把想学的知识点一个个聊出来。\n"
                "批量队列需要一份现成的知识点清单来排队。")
            return
        if self._batch_worker is not None and self._batch_worker.isRunning():
            QMessageBox.information(self, "正在批量处理", "上一批还没跑完，等它结束再来。")
            return

        dlg = BatchDialog(self.knowledge_points, self,
                          default_quality=self._batch_quality)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        idxs, quality = dlg.selection()
        if not idxs:
            self.statusBar().showMessage("没有勾选任何知识点", 4000)
            return
        self._batch_quality = quality
        items = [self.knowledge_points[i] for i in idxs
                 if 0 <= i < len(self.knowledge_points)]
        if items:
            self._start_batch(items, quality)

    def _start_batch(self, items: list[dict], quality: str):
        self._batch_last_mp4 = ""
        self.batch_bar.setRange(0, len(items))
        self.batch_bar.setValue(0)
        self.batch_bar.setFormat("批量 %v/%m")
        self.batch_bar.show()
        self.btn_batch_stop.setEnabled(True)
        self.btn_batch_stop.show()
        self.tabs.setCurrentIndex(1)      # 切到日志页看过程
        self._log(f"[批量] 排队 {len(items)} 个知识点，画质 {quality}，串行执行")

        worker = BatchWorker(items, quality, self._current_domain(),
                             self.course_text, layout=self._current_layout())
        # log / done / fail 由 _run_worker 统一接（这里再接一次日志会打两遍）
        worker.progress.connect(self._on_batch_progress)
        worker.item_done.connect(self._on_batch_item)
        self._batch_worker = worker
        self._run_worker(worker, self._on_batch_done,
                         lambda e: self._log(f"[批量] {e}"))

    def _stop_batch(self):
        if self._batch_worker is not None:
            self._batch_worker.cancel()
            self.btn_batch_stop.setEnabled(False)
            self._log("[批量] 已请求停止：当前这一支渲完后退出")

    def _on_batch_progress(self, done: int, total: int, title: str):
        self.batch_bar.setValue(done)
        self.statusBar().showMessage(f"批量：正在处理「{title}」（{done + 1}/{total}）")

    def _on_batch_item(self, title: str, code: str, mp4: str, err: str):
        """每个知识点跑完立刻落盘：成了存脚本+成片路径，败了只记日志不中断队列。"""
        if err:
            return    # 失败原因 worker 已经在日志里写过了，这里不重复刷一遍
        domain = self._current_domain()
        kp = next((k for k in self.knowledge_points
                   if (k.get("title") or "").strip() == title), {})
        desc = kp.get("description", "")
        scene = ""
        if code:
            names = renderer._scene_class_names(code)
            scene = names[0] if names else ""
            cache.save(domain, title, desc, code, scene_name=scene,
                       level=kp.get("level", ""), source="batch")
        if mp4:
            cache.record_video(domain, title, desc, mp4, code=code, scene_name=scene)
            self._batch_last_mp4 = mp4
        self._log(f"[批量] ✓ {title} → {mp4}" if mp4 else f"[批量] ✓ {title}（未出片）")

    def _on_batch_done(self, ok_n: int, total: int, cancelled: bool):
        self.batch_bar.hide()
        self.btn_batch_stop.hide()
        self._batch_worker = None
        self._refresh_history()
        self._refresh_point_marks()
        failed = max(0, total - ok_n)
        verb = "已停止" if cancelled else "结束"
        msg = f"批量{verb}：成功 {ok_n}/{total}"
        if failed:
            msg += f"，失败 {failed}（原因见日志）"
        self._log(f"[批量] {msg}")
        self.statusBar().showMessage(msg, 8000)
        if self._batch_last_mp4:
            self._load_video(self._batch_last_mp4)
            self.tabs.setCurrentIndex(0)
        if failed and not cancelled:
            QMessageBox.information(
                self, "批量完成",
                f"{msg}\n\n失败的那几个可以单独双击进去、改改描述再生成 —— "
                "批量是流水线，不负责猜你想要什么。")

    def _show_render_failure(self, log_text: str, title: str = "渲染未成功"):
        """渲染失败时先给"人话诊断"，认不出来才甩原始日志。"""
        code = self.editor.toPlainText()
        diag = diagnose.diagnose_text(log_text or "", code)
        if diag:
            self._log("[诊断] 匹配到可能的原因：\n" + diag)
            body = diag + "\n\n（完整日志见「运行日志」页）"
        else:
            self._log("[诊断] 没匹配到常见错误类型，请看原始日志尾部")
            body = "没认出常见错误类型，原始日志尾部如下：\n\n" + \
                (log_text or "")[-900:]
        QMessageBox.warning(self, title, body)

    # ---------- 槽：导出 GIF / 关键帧

    def _export_stem(self) -> str:
        return self.current_point_title or (
            os.path.splitext(os.path.basename(self.current_video or ""))[0]
            or "导出")

    def _after_export(self, ok: bool, path: str, msg: str):
        self._log(msg)
        if not ok:
            QMessageBox.warning(self, "导出失败", msg or "未知原因")
            return
        ans = QMessageBox.question(
            self, "导出完成",
            f"{msg}\n\n要打开所在文件夹看看吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes)
        target = path if Path(path).exists() else Path(path).parent
        if ans == QMessageBox.StandardButton.Yes:
            try:
                if target.is_dir():
                    os.startfile(str(target))   # type: ignore[attr-defined]
                else:
                    subprocess.Popen(["explorer", "/select,", str(target)])
            except Exception as e:
                self._log(f"[导出] 打开文件夹失败：{e}")

    def on_export_gif(self):
        if not self.current_video:
            QMessageBox.information(self, "提示", "还没有可导出的视频")
            return
        self._run_worker(
            ExportWorker("gif", self.current_video, self._export_stem(),
                         max_seconds=20),
            lambda ok, p, m: self._after_export(ok, p, m),
            lambda e: QMessageBox.warning(self, "导出失败", e))
        self.statusBar().showMessage("正在导出 GIF……")

    def on_export_frames(self):
        if not self.current_video:
            QMessageBox.information(self, "提示", "还没有可导出的视频")
            return
        self._run_worker(
            ExportWorker("frames", self.current_video, self._export_stem(),
                         count=12),
            lambda ok, p, m: self._after_export(ok, p, m),
            lambda e: QMessageBox.warning(self, "导出失败", e))
        self.statusBar().showMessage("正在抽取关键帧……")

    def on_export_handout(self):
        if not self.current_video:
            QMessageBox.information(self, "提示", "还没有成片 —— 关键帧要从成片里抽")
            return
        code = self.editor.toPlainText().strip()
        if not code:
            QMessageBox.information(self, "提示", "编辑器里没有脚本，讲义没有内容可抽")
            return
        pack = domains.get_pack(self._current_domain())
        self._run_worker(
            ExportWorker("handout", self.current_video, self._export_stem(),
                         code=code, domain_label=pack.label),
            lambda ok, p, m: self._after_export(ok, p, m),
            lambda e: QMessageBox.warning(self, "讲义生成失败", e))
        self.statusBar().showMessage("正在生成讲义 PDF……")
