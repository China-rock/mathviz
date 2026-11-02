"""问题反馈：把现场信息打包成一段可粘贴的「反馈码」。

为什么不是「点一下直接上报」——这个软件没有服务器，也不能要求使用者注册账号。
所以走「生成一段码 → 粘到微信/QQ/邮件发给作者」这条路：离线可用、不依赖
邮件客户端、也不会被防火墙挡住。

反馈码 = JSON → zlib → base64url，形如

    MXF1-eyJ2IjoxLCJhcHAiOiIxLjAuMCIsImtpbmQiOiJidWci...

里面只有三样东西：使用者填的字段、环境信息、日志尾部。写进码之前统一过
一遍 `redact()`：API Key、Windows 用户名都会被抹掉 —— 反馈是发给别人的，
不能顺带把使用者的密钥和身份送出去。
"""
from __future__ import annotations

import base64
import csv
import datetime
import hashlib
import html
import json
import os
import platform
import re
import sys
import zipfile
import zlib
from pathlib import Path

from . import config

# ---- 作者这边：反馈全部发到这个邮箱
AUTHOR_EMAIL = "china_rock676@163.com"

CODE_PREFIX = "MXF1-"

# 反馈类型：键写进码里，标签只用于显示（改标签不影响解码）
KINDS = {
    "bug": "遇到的问题",
    "idea": "改进建议",
    "other": "其他",
}

# 反馈码里带多少行日志。日志是排查的关键，但码太长在微信里粘不动、
# 邮件客户端也可能截断，所以取一个折中值；完整日志另存在 zip 里。
LOG_LINES_IN_CODE = 60
LOG_LINES_IN_ZIP = 400

# 使用者填的字段上限：码是放进微信/邮件正文的，不能让人把整份日志粘进描述里
MAX_TITLE = 80
MAX_DESC = 4000
MAX_CONTACT = 120

# find_codes 最多从尾部回退多少个字符去找真正的码边界
_MAX_TAIL_TRIM = 24

FEEDBACK_DIR = config.DATA_DIR / "feedback"
INBOX_FILE = FEEDBACK_DIR / "inbox.jsonl"

_KEY_RE = re.compile(r"sk-[A-Za-z0-9_\-]{6,}")


# ---------------------------------------------------------------- 脱敏
def redact(text: str) -> str:
    """抹掉不该外发的东西：API Key、用户名。

    宁可多抹：反馈的价值在于日志里的报错，而不在于知道使用者叫什么。
    """
    if not text:
        return text
    try:
        key = config.get_api_key() or ""
    except Exception:
        key = ""
    if key and len(key) > 8:
        text = text.replace(key, "sk-***")
    text = _KEY_RE.sub("sk-***", text)

    # 路径里的用户名：C:\Users\zhangsan\... -> C:\Users\<用户>\...
    try:
        home = str(Path.home())
        name = Path(home).name
        if name and len(name) > 1:
            text = text.replace(home, r"C:\Users\<用户>" if sys.platform == "win32" else "<HOME>")
            text = re.sub(r"(?i)(users)[\\/]" + re.escape(name) + r"(?=[\\/]|\b)",
                          r"\1\\<用户>", text)
            text = re.sub(r"(?i)(home)[/]" + re.escape(name) + r"(?=[/]|\b)",
                          r"\1/<用户>", text)
    except Exception:
        pass
    return text


# ---------------------------------------------------------------- 环境信息
def collect_env() -> dict:
    """采集排查问题真正用得上的那几项。字段名直接用中文，方便作者阅读。"""
    env: dict[str, str] = {
        "软件版本": config.APP_VERSION,
        "运行方式": "打包版" if config.IS_FROZEN else "源码运行",
        "操作系统": platform.platform(),
        "Python": platform.python_version(),
    }
    try:
        import PySide6
        env["PySide6"] = PySide6.__version__
    except Exception:
        env["PySide6"] = "未知"
    try:
        import manim
        env["Manim"] = getattr(manim, "__version__", "未知")
    except Exception:
        env["Manim"] = "未安装"
    try:
        from . import texenv
        ok, detail = texenv.check()
        first = (detail or "").strip().splitlines()
        env["LaTeX"] = ("就绪" if ok else "缺失") + (f"（{first[0]}）" if first else "")
    except Exception as exc:
        env["LaTeX"] = f"检测失败：{exc}"
    env["渲染目录"] = str(config.RENDER_WORK_DIR)
    env["数据目录"] = str(config.DATA_DIR)
    return {k: redact(str(v)) for k, v in env.items()}


def _tail(path: Path, max_lines: int) -> str:
    """读文件尾部若干行（日志文件可能几百 MB，不能整个读进来）。"""
    try:
        if not path.exists():
            return ""
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            block = min(size, max(64 * 1024, max_lines * 200))
            f.seek(size - block)
            raw = f.read().decode("utf-8", errors="ignore")
        return "\n".join(raw.splitlines()[-max_lines:])
    except Exception as exc:
        return f"（读取 {path.name} 失败：{exc}）"


def collect_logs(max_lines: int = LOG_LINES_IN_CODE) -> dict:
    logs_dir = config.DATA_DIR / "logs"
    return {
        "console": redact(_tail(logs_dir / "console.log", max_lines)),
        "crash": redact(_tail(logs_dir / "crash.log", min(max_lines, 120))),
    }


# ---------------------------------------------------------------- 反馈包
def _clip(text: str, limit: int) -> str:
    """截断超长字段，并在末尾留个省略号（自己写的窗口里也会提示字数）。"""
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def build_packet(kind: str, title: str, desc: str, contact: str = "",
                 include_env: bool = True,
                 log_lines: int = LOG_LINES_IN_CODE,
                 context: str = "") -> dict:
    """把一次反馈拼成 dict。context 是打开反馈窗口时软件的现场状况（可选）。"""
    now = datetime.datetime.now()
    return {
        "v": 1,
        "app": config.APP_VERSION,
        "ts": now.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": kind if kind in KINDS else "other",
        "title": _clip(title, MAX_TITLE),
        "desc": _clip(desc, MAX_DESC),
        "contact": _clip(contact, MAX_CONTACT),
        "frozen": bool(config.IS_FROZEN),
        "env": collect_env() if include_env else {},
        "logs": collect_logs(log_lines) if include_env else {},
        "context": _clip(redact(context or ""), MAX_DESC),
    }


def encode(packet: dict) -> str:
    raw = json.dumps(packet, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    body = base64.urlsafe_b64encode(zlib.compress(raw, 9)).decode("ascii")
    return CODE_PREFIX + body.rstrip("=")


def _decode_body(body: str) -> dict:
    """解一段 base64url 码体。失败一律抛异常，由上层决定怎么解释。

    这里用 decompressobj 而不是 zlib.decompress：后者会**静默忽略**尾部的多余字节，
    "码 + 紧跟着的一串英文"照样能解出来 —— 那样就没法靠"能不能解"来判断
    码的真实边界了。eof 检查数据完整性，unused_data 检查后面有没有多出来的东西。
    """
    if len(body) % 4 == 1:          # base64 无 padding 时长度只可能是 0/2/3
        raise ValueError("反馈码长度不对")
    padded = body + "=" * (-len(body) % 4)
    data = base64.urlsafe_b64decode(padded.encode("ascii"))
    obj = zlib.decompressobj()
    raw = obj.decompress(data) + obj.flush()
    if not obj.eof:
        raise ValueError("反馈码不完整（数据没到底）")
    if obj.unused_data:
        raise ValueError("反馈码后面还有多余内容")
    packet = json.loads(raw.decode("utf-8"))
    if not isinstance(packet, dict):
        raise ValueError("反馈码内容不是合法结构")
    return packet


def _body_of(code: str) -> str:
    """从任意一段文字里取出码体（`MXF1-` 之后的部分），去掉换行等噪音。"""
    s = re.sub(r"\s+", "", code or "")
    i = s.find(CODE_PREFIX)
    if i < 0:
        return ""
    return re.sub(r"[^A-Za-z0-9_\-]", "", s[i + len(CODE_PREFIX):])


def normalize_code(code: str) -> str:
    """把带尾巴的码裁到刚好吃得下的长度，返回规范化后的完整码。

    聊天软件里码后面常紧跟英文或数字（"MXF1-xxx 谢谢"、"MXF1-xxx1"、没有空格时
    就成了 "MXF1-xxxthanks"）。正则只能贪婪地一路吃到非 base64 字符为止，多出来的
    尾巴会让 zlib 校验失败。zlib 自带校验和，所以"从长到短试"是可靠的：
    第一个能解开的长度就是真正的码边界。
    """
    body = _body_of(code)
    if not body:
        return ""
    for cut in range(0, min(_MAX_TAIL_TRIM, len(body))):
        cand = body[: len(body) - cut] if cut else body
        try:
            _decode_body(cand)
            return CODE_PREFIX + cand
        except Exception:
            continue
    return CODE_PREFIX + body      # 都解不开：原样返回，让上层给出可读的错误


def decode(code: str) -> dict:
    """解析反馈码。宽容处理：聊天软件会在长文本里插换行，先全部去掉空白。"""
    if not _body_of(code):
        raise ValueError("这段文字里没找到反馈码（应以 MXF1- 开头）")
    body = normalize_code(code)[len(CODE_PREFIX):]
    try:
        return _decode_body(body)
    except Exception as e:
        # zlib 的原话是 "Error -5 while decompressing data"，直接抛给界面等于没说
        raise ValueError(
            "反馈码不完整或已损坏（很可能被聊天软件截断了）。\n"
            "请让反馈人重新点一次「复制反馈码」，整段粘过来再试。") from e


def find_codes(text: str) -> list[str]:
    """从一大段聊天记录里抠出所有反馈码（一次粘多条也认）。

    两条码连着粘时，去空白后中间没有分隔符（"…码A码B"），所以用非贪婪 + 前瞻：
    一遇到下一个 `MXF1-` 或非 base64 字符就收尾。每个候选再过一遍 normalize_code，
    这样"复制码 + 直接接着打英文"也能裁回真正的边界。
    """
    s = re.sub(r"\s+", "", text or "")
    if CODE_PREFIX not in s:
        return []
    pat = re.compile(re.escape(CODE_PREFIX) + r"([A-Za-z0-9_\-]+?)(?="
                     + re.escape(CODE_PREFIX) + r"|[^A-Za-z0-9_\-]|$)")
    out: list[str] = []
    for m in pat.finditer(s):
        code = normalize_code(CODE_PREFIX + m.group(1))
        if code and code != CODE_PREFIX:
            out.append(code)
    return out


def packet_id(code: str) -> str:
    return hashlib.sha1(code.encode("utf-8")).hexdigest()[:12]


def kind_label(packet: dict) -> str:
    return KINDS.get(packet.get("kind", "other"), "其他")


# ---------------------------------------------------------------- 落盘
def _stamp() -> str:
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


def save_zip(packet: dict) -> Path:
    """把完整反馈存成 zip（含更长的日志），作为邮件附件用。"""
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    tag = packet_id(encode(packet))
    path = FEEDBACK_DIR / f"feedback-{_stamp()}-{tag}.zip"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("feedback.json",
                   json.dumps(packet, ensure_ascii=False, indent=2))
        z.writestr("feedback.txt", pretty_text(packet))
        for name, text in (packet.get("logs") or {}).items():
            if text:
                z.writestr(f"logs/{name}.log", text)
    return path


def pretty_text(packet: dict) -> str:
    """人读版：邮件正文、反馈台详情都用它。"""
    lines = [
        f"类型：{kind_label(packet)}",
        f"标题：{packet.get('title') or '（未填）'}",
        f"时间：{packet.get('ts', '')}",
        f"联系方式：{packet.get('contact') or '（未填）'}",
        "",
        "【描述】",
        packet.get("desc", ""),
    ]
    if packet.get("context"):
        lines += ["", "【现场】", packet["context"]]
    if packet.get("env"):
        lines += ["", "【环境】"]
        lines += [f"  {k}：{v}" for k, v in packet["env"].items()]
    for name, title in (("console", "运行日志"), ("crash", "崩溃日志")):
        text = (packet.get("logs") or {}).get(name, "")
        if text:
            lines += ["", f"【{title}】", text]
    return redact("\n".join(lines))


# ---------------------------------------------------------------- 邮件
def mailto_url(code: str, packet: dict, to: str = AUTHOR_EMAIL) -> str:
    """拼 mailto 链接：收件人、主题、正文（含反馈码）全部预填。

    正文刻意写得极简 —— 只放码和一句说明。原因是 mailto 走的是命令行式的
    URL，很多邮件客户端在 2000 字符左右会截断，而中文经 URL 编码后一个字符
    要占 9 个字符位；若把环境信息和日志摘要也塞进正文，光正文就能吃掉几千位，
    码必然被截断、拆出来就是乱码。摘要与日志本来就在码里，反馈台能展开看。

    顺带：正文里放不了附件，所以 zip 只能由用户自己拖进邮件，界面会告诉他路径。
    """
    from urllib.parse import quote

    subject = f"【MathViz 反馈】{kind_label(packet)}：{packet.get('title') or '无标题'}"
    body = ("以下为 MathViz 自动生成的反馈码，请勿修改，直接发送即可。\n\n"
            f"{code}\n")
    return (f"mailto:{to}?subject={quote(subject)}&body={quote(body)}")


# 邮件客户端对 mailto 长度的实际容忍度：取一个保守值，宁可少带日志也别让码被截断
MAILTO_MAX = 1900


def fit_for_mailto(build, to: str = AUTHOR_EMAIL):
    """挑一个能塞进 mailto 的版本：先试完整日志，超长就逐级减少行数。

    build(n) 必须返回一个 packet（n = 日志行数）。返回 (码, 包, 链接, 行数)。
    """
    result = ("", {}, "", 0)
    for n in (LOG_LINES_IN_CODE, 25, 0):
        packet = build(n)
        code = encode(packet)
        url = mailto_url(code, packet, to)
        result = (code, packet, url, n)
        if len(url) <= MAILTO_MAX:
            return result
    return result


# ---------------------------------------------------------------- 收件箱（作者端）
def load_items() -> list[dict]:
    items: list[dict] = []
    if not INBOX_FILE.exists():
        return items
    for line in INBOX_FILE.read_text(encoding="utf-8", errors="ignore").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    # 文件是"追加写"的，所以倒过来就是新的在前；再按收到时间稳定排序 ——
    # 同一秒内导入的多条，靠这一步也能保持"后导入的排上面"。
    items.reverse()
    items.sort(key=lambda it: it.get("received", ""), reverse=True)
    return items


def _write_items(items: list[dict]) -> None:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    # 先写临时文件再替换：中途崩溃不会把历史反馈整份写坏
    tmp = INBOX_FILE.with_suffix(".jsonl.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        for it in items:
            f.write(json.dumps(it, ensure_ascii=False) + "\n")
    os.replace(tmp, INBOX_FILE)


def add_code(code: str) -> tuple[dict, bool]:
    """导入一条反馈码。返回 (条目, 是否新增)；重复的码不会重复入库。"""
    packet = decode(code)
    fid = packet_id(code)
    items = load_items()
    if any(it.get("id") == fid for it in items):
        return next(it for it in items if it.get("id") == fid), False
    item = {
        "id": fid,
        "received": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "status": "new",
        "code": code,
        "packet": packet,
    }
    items.append(item)
    _write_items(items)
    return item, True


def add_zip(path: Path) -> tuple[dict, bool]:
    """导入邮件附件里的 zip（作者把同学发来的附件拖进来即可）。"""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        if "feedback.json" in names:
            packet = json.loads(z.read("feedback.json").decode("utf-8"))
            code = encode(packet)
        else:
            raise ValueError("这个 zip 里没有 feedback.json，不像是反馈包")
    return add_code(code)


def set_status(fid: str, status: str) -> None:
    items = load_items()
    for it in items:
        if it.get("id") == fid:
            it["status"] = status
    _write_items(items)


def delete_item(fid: str) -> None:
    _write_items([it for it in load_items() if it.get("id") != fid])


def export_csv(path: Path, items: list[dict]) -> Path:
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["收到时间", "类型", "标题", "描述", "联系方式",
                    "软件版本", "操作系统", "状态"])
        for it in items:
            p = it.get("packet", {})
            w.writerow([it.get("received", ""), kind_label(p),
                        p.get("title", ""), p.get("desc", ""),
                        p.get("contact", ""), p.get("app", ""),
                        (p.get("env") or {}).get("操作系统", ""),
                        "已处理" if it.get("status") == "done" else "待处理"])
    return path


def export_markdown(path: Path, items: list[dict]) -> Path:
    path = Path(path)
    out = [f"# MathViz 反馈汇总（{datetime.date.today().isoformat()}）", ""]
    for it in items:
        p = it.get("packet", {})
        out += [
            f"## {p.get('title') or '（无标题）'}",
            f"- 类型：{kind_label(p)}",
            f"- 时间：{p.get('ts', '')}（收到 {it.get('received', '')}）",
            f"- 联系方式：{p.get('contact') or '未填'}",
            f"- 版本：{p.get('app', '')} · {(p.get('env') or {}).get('操作系统', '')}",
            "",
            html.unescape(p.get("desc", "")).strip(),
            "",
        ]
    path.write_text("\n".join(out), encoding="utf-8")
    return path


def open_folder() -> Path:
    FEEDBACK_DIR.mkdir(parents=True, exist_ok=True)
    return FEEDBACK_DIR
