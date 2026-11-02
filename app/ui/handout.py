"""讲义 PDF：脚本里的中文解说 + 成片关键帧 → 一页 A4，零新增依赖。

设计取舍：
- 不引 reportlab / weasyprint 这类第三方库 —— Qt 自带的 QPdfWriter 就能出
  矢量中文（可搜索、可复制、打印清晰）。注意：在 QT_QPA_PLATFORM=offscreen 的
  测试环境里文字会被栅格化成位图（那套平台没有可用的字形引擎），真实桌面运行
  才是矢量输出 —— 别被 offscreen 下 pypdf 提取不到文本吓到。
- 公式不进讲义：MathTex 的 LaTeX 源码印在纸上没法读，用 mathtext 重渲染又有
  "命令不完全兼容"的坑。讲义以中文解说 + 画面为主 —— 画面本身就是答案。
- 文案只从 Text("...") 的字面量抽：那是 AI 按提示词规范写的解说行，
  MathTex 里的符号（k、\\Delta）抽出来也没有阅读价值。
"""
import ast
import html as html_mod
import time
from pathlib import Path

from PySide6.QtCore import QSizeF
from PySide6.QtGui import QPageSize, QPdfWriter, QTextDocument

from app.core import renderer
from app.core.config import OUTPUT_MEDIA_DIR


def extract_narration(code: str) -> list[str]:
    """按出现顺序抽取脚本里的中文解说（Text 的字面量字符串）。

    过滤规则：
    - 汉字不足 2 个的丢弃（"k"、"↑" 这类符号标签没有阅读价值）
    - 同一句话只保留第一次（循环里反复 Transform 的那句不该出现 N 遍）
    """
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
             and n.func.id in ("Text", "Paragraph", "MarkupText")]
    calls.sort(key=lambda n: getattr(n, "lineno", 0))
    seen: set[str] = set()
    out: list[str] = []
    for node in calls:
        for a in list(node.args) + [kw.value for kw in node.keywords]:
            if isinstance(a, ast.Constant) and isinstance(a.value, str):
                s = a.value.strip()
                if sum(1 for ch in s if "\u4e00" <= ch <= "\u9fff") < 2 or s in seen:
                    continue
                seen.add(s)
                out.append(s)
    return out


def build_handout(title: str, code: str, video_path: str | None,
                  domain_label: str = "", out_path: str | None = None,
                  frame_count: int = 4, log_cb=None) -> tuple[bool, str, str]:
    """生成讲义 PDF。返回 (ok, 输出路径, 消息)。

    关键帧直接从当前成片抽（与用户看到的画面一致）；没有成片就只出文字版。
    输出位置与其他产物一致：media/<知识点>-<时刻>-讲义.pdf。
    """
    narration = extract_narration(code)
    if not narration:
        return False, "", "脚本里没有抽到中文解说（Text 里的字面量），生成不了讲义"

    dest = (Path(out_path) if out_path
            else OUTPUT_MEDIA_DIR / renderer.archive_filename(title, suffix=".pdf"))
    dest.parent.mkdir(parents=True, exist_ok=True)

    video = Path(video_path) if video_path else None
    has_video = bool(video and video.exists())
    dur = renderer.video_duration(video) if has_video else None

    frames: list[Path] = []
    if has_video:
        ok, fdir, _ = renderer.export_frames(str(video), archive_stem=title,
                                             count=frame_count, log_cb=log_cb)
        if ok and fdir:
            frames = sorted(Path(fdir).glob("*.png"))[:frame_count]

    parts: list[str] = [f"<h1 align='center'>{html_mod.escape(title)}</h1>"]
    meta = [html_mod.escape(domain_label)] if domain_label else []
    if dur:
        meta.append(f"成片约 {dur:.0f} 秒")
    meta.append(time.strftime("%Y-%m-%d"))
    parts.append(f"<p align='center'>{' · '.join(meta)}</p><hr>")
    lis = "".join(f"<li>{html_mod.escape(s)}</li>" for s in narration)
    parts.append(f"<h2>讲解要点</h2><ol>{lis}</ol>")
    if frames:
        parts.append("<h2>画面速览</h2>")
        rows = []
        for i in range(0, len(frames), 2):
            cells = "".join(
                f"<td><img src='{f.as_uri()}' width='680'></td>"
                for f in frames[i:i + 2])
            rows.append(f"<tr>{cells}</tr>")
        parts.append("<table cellspacing='10'>" + "".join(rows) + "</table>")
    parts.append("<p align='center'>由 MathViz 自动生成 · 画面以成片为准</p>")

    writer = QPdfWriter(str(dest))
    writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
    writer.setResolution(200)     # 关键帧是位图，200dpi 打印不发虚
    doc = QTextDocument()
    font = doc.defaultFont()
    font.setFamily("Microsoft YaHei")
    font.setPointSize(10.5)
    doc.setDefaultFont(font)
    doc.setPageSize(QSizeF(writer.width(), writer.height()))
    doc.setHtml("".join(parts))
    doc.print_(writer)

    if log_cb:
        log_cb(f"[讲义] 已生成 {dest}")
    return True, str(dest), f"讲义已生成：{dest.name}"
