"""课件解析：pptx / pdf / docx / md / txt / tex → 纯文本。

大文件处理说明：
PPT/DOCX 常因高清图片/视频而虚胖到几百 MB，但文本可能只有几 KB。
这类文件的媒体部分在解析时是被惰性跳过的（实测 448 MB 的 PPT，
python-pptx 提取文本仅需 2.3s），所以体积大本身不构成问题。
`inspect_size()` 用 zip 目录表算出"媒体 vs 文本"的构成，毫秒级判定是否放行。
"""
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from .config import (MAX_CONTENT_TEXT_MB, MAX_COURSETEXT_CHARS,
                     MAX_FILE_SIZE_MB, MAX_FILE_SIZE_MB_HARD,)

MB = 1024 * 1024


class ParseError(Exception):
    pass


@dataclass(frozen=True)
class SizeVerdict:
    """文件大小体检结论。

    level: "ok"（放行） / "notice"（放行但有话说） / "reject"（拒收）
    """
    level: str
    message: str
    media_mb: float = 0.0
    content_mb: float = 0.0

    @property
    def ok(self) -> bool:
        return self.level != "reject"


# 解析器往文本里加的页码标记，统计"真实正文"时要先剔掉
_PAGE_TAG_RE = re.compile(r"【第\s*\d+\s*页】")


def meaningful_chars(text: str) -> int:
    """去掉页码标记后的实际正文字数。

    扫描件 PDF 抽出来的东西长得像这样：
        【第 1 页】\n\n【第 2 页】\n\n【第 3 页】……
    按原始长度算是"有几百字"，但去掉页码标记后一个字都没有 ——
    所以判定"有没有读到东西"必须用这个口径，不能直接 len()。
    """
    return len(_PAGE_TAG_RE.sub("", text or "").strip())


# zip 内部：媒体资源所在目录
_MEDIA_RE = re.compile(r"(?:^|/)(media|embeddings)/", re.I)


def _human(mb: float) -> str:
    return f"{mb:.0f} MB" if mb >= 1 else f"{mb * 1024:.0f} KB"


def inspect_size(path: str | Path) -> SizeVerdict:
    """判定文件是否可以作为课件加载。

    策略（看成分，不看体重）：
    - pptx/docx：读 zip 目录表分离媒体与文本部分 —— 只有"文本部分"超限才拒收
    - pdf：统计各页图像 XObject 的体积，估计出其中的非图像部分
    - md/txt/tex：无内部结构，按总大小判断
    - 一律受 MAX_FILE_SIZE_MB_HARD 绝对上限约束
    """
    p = Path(path)
    suffix = p.suffix.lower()
    try:
        total_mb = p.stat().st_size / MB
    except OSError as e:
        return SizeVerdict("reject", f"无法读取文件：{e}")

    if total_mb > MAX_FILE_SIZE_MB_HARD:
        return SizeVerdict(
            "reject",
            f"该文件 {_human(total_mb)}，超过 {MAX_FILE_SIZE_MB_HARD} MB 上限。\n\n"
            "如此巨大的课件建议按章节拆分后再导入。")

    if suffix in (".pptx", ".docx"):
        try:
            with zipfile.ZipFile(p) as z:
                media = content = 0
                for info in z.infolist():
                    if _MEDIA_RE.search(info.filename):
                        media += info.file_size
                    else:
                        content += info.file_size
        except Exception as e:   # 损坏的 zip：交给后续解析阶段报错
            return SizeVerdict("ok", f"（无法预检内部结构：{e}）")
        media_mb, content_mb = media / MB, content / MB
        share = media / (media + content) if (media + content) else 0.0
        if content_mb > MAX_CONTENT_TEXT_MB:
            return SizeVerdict(
                "reject",
                f"该文件 {_human(total_mb)}，解压后正文部分达 {_human(content_mb)}"
                f"（媒体资源另占 {_human(media_mb)}），超出 {MAX_CONTENT_TEXT_MB} MB 预算。\n\n"
                "这通常对应几百页的完整讲义/教材，AI 上下文装不下，"
                "建议按章节拆分后分别导入。",
                media_mb, content_mb)
        if media_mb > 1:
            return SizeVerdict(
                "notice",
                f"文件 {_human(total_mb)}，其中解压后有 {_human(media_mb)} 是"
                f"图片/视频等媒体资源（占 {share:.0%}）。\n这些媒体不会被解析，"
                "文本提取不受影响 —— 但若课件内容主要印在图片上（扫描件），"
                "提取不到文字属正常现象。",
                media_mb, content_mb)
        return SizeVerdict("ok", "", media_mb, content_mb)

    if suffix == ".pdf":
        if total_mb <= MAX_FILE_SIZE_MB:
            return SizeVerdict("ok", "", 0.0, total_mb)
        # 大 PDF：用抽样文本探针判断成分。
        # 不用"统计图像 XObject 体积"那套办法 —— 扫描件/导出型 PDF 常把图作为
        # inline image（BI...ID...EI）直接嵌进内容流，那里数不出 XObject，
        # 会把图片型 PDF 误判成"全是文字"而拒收（实测踩过）。
        est_chars = _pdf_text_probe(p)
        if est_chars is None:      # 加密/损坏等：退回朴素的总大小判断
            return _plain_file_verdict(total_mb)
        if est_chars > MAX_COURSETEXT_CHARS * 3:
            return SizeVerdict(
                "reject",
                f"该文件 {_human(total_mb)}，抽样估算其中约有 {est_chars / 10000:.1f} 万字正文，"
                f"远超 AI 一次能处理的规模（约 {MAX_COURSETEXT_CHARS} 字符）。\n\n"
                "上百页的完整讲义/教材请按章节拆分后分别导入。",
                0.0, total_mb)
        if est_chars < 200:
            return SizeVerdict(
                "notice",
                f"文件 {_human(total_mb)}，但抽样几页几乎没有提取出文字"
                "（预估全文不足 200 字）。\n\n"
                "这大概率是**扫描件或图片导出型 PDF**：字印在图里，"
                "文本层是空的。请先 OCR，或直接改用带文字层的源文件。",
                0.0, total_mb)
        if est_chars > MAX_COURSETEXT_CHARS:
            return SizeVerdict(
                "notice",
                f"文件 {_human(total_mb)}，抽样估算约有 {est_chars / 10000:.1f} 万字正文，"
                f"超出 AI 上下文预算的部分将被自动截断。\n"
                "若希望覆盖全文，建议按章节拆分后分别导入。",
                0.0, total_mb)
        return SizeVerdict("ok", "", 0.0, total_mb)

    return _plain_file_verdict(total_mb)


def _plain_file_verdict(total_mb: float) -> SizeVerdict:
    """无内部结构的纯文本文件（md/txt/tex）：按总大小判断。"""
    if total_mb > MAX_FILE_SIZE_MB:
        return SizeVerdict(
            "reject",
            f"该文件 {_human(total_mb)}，超过 {MAX_FILE_SIZE_MB} MB 门槛。\n\n"
            "AI 的上下文容量有限，超大课件通常是整本书或整学期讲义，"
            "提取质量会明显下降。建议按章节拆分后分别导入。")
    return SizeVerdict("ok", "", 0.0, total_mb)


def _pdf_text_probe(p: Path, samples: int = 8) -> float | None:
    """抽样估算 PDF 全文字符数：均匀抽若干页提取文本取均值，再乘总页数。

    只解真正被抽到的页（每张扫描图几十毫秒），不读未抽样的页。
    返回估算字符数；文件加密或无法解析时返回 None（由调用方退回朴素判断）。
    """
    try:
        from pypdf import PdfReader
        reader = PdfReader(str(p))
    except Exception:
        return None
    try:
        if getattr(reader, "is_encrypted", False):
            try:
                reader.decrypt("")
            except Exception:
                return None
        n = len(reader.pages)
        if n <= 0:
            return None
        picks = {0, n - 1, n // 2} | {
            round(i * (n - 1) / max(1, samples - 1)) for i in range(samples)}
        picks = sorted(i for i in picks if 0 <= i < n)
        chars = 0
        for i in picks:
            try:
                chars += len(reader.pages[i].extract_text() or "")
            except Exception:
                continue
        return chars / max(1, len(picks)) * n
    except Exception:
        return None


def parse_file(path: str | Path) -> str:
    p = Path(path)
    if not p.exists():
        raise ParseError(f"文件不存在: {p}")
    suffix = p.suffix.lower()
    if suffix == ".pdf":
        text = _parse_pdf(p)
    elif suffix == ".pptx":
        text = _parse_pptx(p)
    elif suffix == ".docx":
        text = _parse_docx(p)
    elif suffix in (".md", ".txt", ".tex"):
        text = p.read_text(encoding="utf-8", errors="ignore")
    else:
        raise ParseError(f"暂不支持的格式: {suffix}（支持 pdf/pptx/docx/md/txt/tex）")
    return _truncate(text)


def _parse_pdf(p: Path) -> str:
    from pypdf import PdfReader
    reader = PdfReader(str(p))
    pages = []
    for i, page in enumerate(reader.pages, 1):
        try:
            content = page.extract_text() or ""
        except Exception:
            content = ""
        pages.append(f"【第 {i} 页】\n{content.strip()}")
    return "\n\n".join(pages)


def _parse_pptx(p: Path) -> str:
    from pptx import Presentation
    prs = Presentation(str(p))
    slides = []
    for i, slide in enumerate(prs.slides, 1):
        parts = [f"【第 {i} 页】"]
        for shape in slide.shapes:
            if shape.has_text_frame:
                txt = shape.text_frame.text.strip()
                if txt:
                    parts.append(txt)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    cells = [c.text.strip() for c in row.cells]
                    parts.append(" | ".join(cells))
        slides.append("\n".join(parts))
    return "\n\n".join(slides)


def _parse_docx(p: Path) -> str:
    import docx
    document = docx.Document(str(p))
    paras = [para.text.strip() for para in document.paragraphs if para.text.strip()]
    for table in document.tables:
        for row in table.rows:
            paras.append(" | ".join(c.text.strip() for c in row.cells))
    return "\n\n".join(paras)


def _truncate(text: str) -> str:
    if len(text) > MAX_COURSETEXT_CHARS:
        head = text[: MAX_COURSETEXT_CHARS // 2]
        tail = text[-MAX_COURSETEXT_CHARS // 2 :]
        return head + "\n\n……【中间内容过长已截断】……\n\n" + tail
    return text
