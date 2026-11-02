"""渲染失败诊断：把一坨 traceback 翻译成"哪里错 + 怎么改"。

manim 的报错信息对开发者友好、对使用者很不友好：真正的病因常常埋在几十行
中间产物日志里，而抛在最末尾的往往只是"子进程返回非 0"这种废话。
本模块用一组规则去匹配**原始日志**，命中就给出：标题 / 为什么 / 怎么改。
命中不了就老实说"没认出来"，绝不瞎猜误导人。
"""
import re
from dataclasses import dataclass

_max = 3   # 最多返回几条：人一次只看得进这么多


@dataclass
class Diagnosis:
    title: str
    why: str
    fix: str
    evidence: str = ""      # 触发这条判断的那一行（给心里有数的人查）

    def text(self) -> str:
        head = f"• {self.title}：{self.why}"
        tail = f"  怎么改：{self.fix}"
        if self.evidence:
            tail += f"\n  线索：{self.evidence[:120]}"
        return head + "\n" + tail


# ---------------------------------------------------------------- 代码静态线索

_CJK = re.compile(r"[\u4e00-\u9fff]")
_MATHTEX_CALL = re.compile(r"MathTex\s*\((.*?)\)", re.S)


def chinese_in_mathtex(code: str) -> str | None:
    """MathTex 里混进了中文：LaTeX 不认 CJK 字符，必然编译失败。"""
    if not code:
        return None
    for m in _MATHTEX_CALL.finditer(code):
        arg = m.group(1)
        if _CJK.search(arg):
            line_no = code[:m.start()].count("\n") + 1
            hit = next(_CJK.finditer(arg), None)
            return f"第 {line_no} 行的 MathTex 里有中文「{hit.group(0) if hit else ''}」"
    return None


def _scene_line(code: str, needle: str) -> str | None:
    for i, ln in enumerate((code or "").splitlines(), 1):
        if needle in ln:
            return f"第 {i} 行：{ln.strip()[:100]}"
    return None


# ---------------------------------------------------------------- 规则表

def _rule(title: str, why: str, fix: str):
    return (title, why, fix)


def diagnose(error_text: str, code: str = "") -> list[Diagnosis]:
    """根据渲染日志给出诊断。返回可能为空（没认出来）。"""
    t = error_text or ""
    low = t.lower()
    out: list[Diagnosis] = []

    def hit(keywords, evidence_key=None):
        """在日志里找关键词，返回命中的那一行。"""
        for ln in t.splitlines():
            l = ln.lower()
            if all(k in l for k in keywords):
                return ln.strip()[:160]
        return (evidence_key if evidence_key in low else None)

    # 1) LaTeX 根本没装 / 不在 PATH
    if "system can't find the file specified" in low or "filenotfounderror" in low:
        ev = hit(["latex"]) or hit(["winerror 2"])
        if ev:
            out.append(Diagnosis(
                "找不到 LaTeX",
                "系统里没有可用的 latex 命令，公式渲染必然失败。",
                "安装 MiKTeX（勾选『自动安装缺失宏包』）后重启 MathViz；"
                "或手动把 MiKTeX 的 bin\\x64 目录加进 PATH。",
                ev))

    # 2) 缺宏包
    if "not found" in low and (".sty" in low or "package" in low):
        ev = hit(["not found"])
        out.append(Diagnosis(
            "缺少 LaTeX 宏包",
            "脚本用到的宏包在本机 LaTeX 发行版里没有安装。",
            "打开 MiKTeX Console 勾选『自动安装缺失宏包』再重试；"
            "离线安装则需要手动安装对应 package。",
            ev or ""))

    # 3) LaTeX 编译失败（最常见的一坨）
    if "latex error" in low or "latexerror" in low or "see the transcription log" in low:
        ev = chinese_in_mathtex(code)
        if ev:
            # 病因已经具体到"中文进了数学模式"，标题就别说成笼统的编译失败
            out.append(Diagnosis(
                "MathTex 里混进了中文",
                "公式里混了中文——LaTeX 的数学模式不认汉字，编译必然失败。",
                "把中文挪到 MathTex 外面，用 Text(\"…\") 或 "
                "VGroup(Text(\"…\"), MathTex(…)) 拼装。",
                ev))
        else:
            out.append(Diagnosis(
                "公式编译失败",
                "LaTeX 编译源文件失败，通常是某个公式的写法不合法。",
                "点开日志看 LaTeX 段的上方几行，那里标着出错的公式；"
                "常见原因是用了不支持的命令。",
                hit(["latex"]) or ""))

    # 4) 未定义的 LaTeX 命令
    if "undefined control sequence" in low:
        out.append(Diagnosis(
            "用了不存在的 LaTeX 命令",
            "公式里写了 LaTeX 不认识的控制序列（也可能缺宏包）。",
            "检查拼写，或改用 manim 的 Matrix / Tex 等现成 mobject。",
            hit(["undefined control sequence"]) or ""))

    # 5) 中文进了 MathTex（即便没走到 LaTeX 报错也值得提醒）
    ev = chinese_in_mathtex(code)
    if ev and not any(d.title == "公式编译失败" for d in out):
        out.append(Diagnosis(
            "MathTex 里混进了中文",
            "数学模式下汉字会被当成非法命令处理。",
            "中文用 Text() 渲染，公式用 MathTex()，两者用 VGroup 组合排版。",
            ev))

    # 6) 字体问题
    if ("unknown file type" in low or "font" in low and "not found" in low
            or "glyph" in low):
        out.append(Diagnosis(
            "字体不可用",
            "脚本里指定的字体在本机不存在（项目默认写的是 Microsoft YaHei）。",
            "macOS / Linux 或精简版 Windows 需在脚本里换成系统已装的字体。",
            hit(["font"]) or _scene_line(code, "font=") or ""))

    # 7) 文件被占用
    if "permissionerror" in low or "winerror 32" in low:
        out.append(Diagnosis(
            "文件被别的程序占用",
            "上一支视频多半正被播放器或预览窗口占着，新片写不进去。",
            "关掉正在播放的窗口（含系统播放器）后重新渲染。",
            hit(["permissionerror"], "winerror 32") or ""))

    # 8) 路径非法
    if "errno 22" in low or "invalid argument" in low:
        out.append(Diagnosis(
            "路径里有空格或特殊字符",
            "LaTeX 在带空格 / 中文的路径下会闹脾气，这是它的兼容性要求。",
            "渲染工作目录已经固定在无空格路径；若手动改过 "
            "MATHVIZ_WORK_DIR，请换成纯英文短路径。",
            hit(["errno 22"]) or ""))

    # 9) 幻觉 API / 未定义对象
    m = re.search(r"NameError: name '(\w+)' is not defined", t)
    if m:
        out.append(Diagnosis(
            f"用了不存在的对象 {m.group(1)}",
            "AI 偶尔会凭空捏造 mobject 名字（常见：Wave、ParametricCurve3D 的变体、自造类）。",
            "用「🛠 代码修改模式」告诉它这个对象不存在、换成 manim 标准 API；"
            "或直接点生成重做一版。",
            _scene_line(code, m.group(1)) or ""))

    # 10) 超时
    if "渲染超时" in t or "timeoutexpired" in low:
        out.append(Diagnosis(
            "渲染超时",
            "动画太长或机器太忙，超过了单次渲染的时间上限（15 分钟）。",
            "缩短脚本：减少 wait、降低分段数，或先用低画质跑通再上高清。",
            ""))

    # 11) 语法错误（静态检查拦得住，但手改后可能漏进来）
    if "syntaxerror" in low or "indentationerror" in low:
        out.append(Diagnosis(
            "脚本语法错误",
            "代码本身不合法，manim 还没开始渲染就退出了。",
            "看日志里指出的行号修掉（常见是引号没闭合、缩进错位）。",
            hit(["syntaxerror"], "indentationerror") or ""))

    # 12) ndarray / 参数类错误
    if "broadcast" in low or "matmul" in low or "operands could not" in low:
        out.append(Diagnosis(
            "数值参数不合法",
            "传给动画 / 坐标的数据维度对不上（典型是标量与数组混用）。",
            "用「🛠 代码修改模式」描述报错让它修；多数是 np.array 与 float 混用。",
            hit(["broadcast"]) or ""))

    return out[:_max]


def diagnose_text(error_text: str, code: str = "") -> str:
    """给 UI 用的一大段文本；没命中时返回空串由调用方决定要不要显示原始错误。"""
    ds = diagnose(error_text, code)
    if not ds:
        return ""
    return "\n".join(d.text() for d in ds)
