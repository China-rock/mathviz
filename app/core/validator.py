"""渲染前的静态检查：语法、场景类、危险 import、MathTex 中的非 ASCII 字符、未定义名。"""
import ast
import builtins

# 这些类走 LaTeX 编译通道，里面不能出现中文等 UTF-8 字符
_TEX_CLASSES = {"MathTex", "Tex", "SingleStringMathTex", "TexText"}

# 内置名 + 少量解释器注入名（不 import 也可用）
_BUILTIN_NAMES = set(dir(builtins)) | {"__name__", "__file__", "__doc__", "__debug__"}

_MANIM_NAMES: set[str] | None = None


def _manim_names() -> set[str]:
    """manim 的完整命名空间（from manim import * 后可用的名字），懒加载缓存。"""
    global _MANIM_NAMES
    if _MANIM_NAMES is None:
        import manim
        _MANIM_NAMES = set(dir(manim))
    return _MANIM_NAMES


def _call_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _literal_strings(node: ast.Call) -> list[tuple[str, int]]:
    """收集调用实参里的字面字符串（含列表/元组内、关键字实参）。"""
    out: list[tuple[str, int]] = []

    def add(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, str):
            out.append((n.value, getattr(n, "lineno", 0)))
        elif isinstance(n, (ast.List, ast.Tuple)):
            for el in n.elts:
                add(el)

    for a in node.args:
        add(a)
    for kw in node.keywords:
        add(kw.value)
    return out


def _collect_defined_names(tree: ast.AST) -> tuple[set[str], bool]:
    """收集全文件"可能已定义"的名字，并返回是否存在 manim 以外的 star import。

    策略是保守的：把所有作用域的定义并成一个集合 —— 宁可漏报，绝不误报。
    （误报会让 AI 白白"修复"一轮，比漏报代价更大。）
    """
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for a in node.names:
                names.add((a.asname or a.name).split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if any(a.name == "*" for a in node.names):
                if node.module == "manim":
                    names |= _manim_names()
                else:
                    return set(), True   # 未知 star import，放弃名字检查
            else:
                for a in node.names:
                    names.add(a.asname or a.name)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Del)):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.ExceptHandler) and node.name:
            names.add(node.name)
        elif isinstance(node, (ast.Global, ast.Nonlocal)):
            names.update(node.names)
        elif hasattr(ast, "MatchAs") and isinstance(node, ast.MatchAs) and node.name:
            names.add(node.name)
    return names, False


def _coord_of(node: ast.Call) -> tuple[float, float] | None:
    """从 move_to(...) 的第一个实参里取出 (x, y)。

    支持 [x, y, 0] / (x, y, 0) / np.array([x, y, 0]) 三种常见写法；
    取不到（变量、表达式、ORIGIN 常量等）就返回 None —— 宁可漏报。
    """

    def num(n):
        if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
            return float(n.value)
        if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
            v = num(n.operand)
            return -v if v is not None else None
        return None

    args = list(node.args) + [kw.value for kw in node.keywords]
    if not args:
        return None
    a = args[0]
    if isinstance(a, ast.Call):          # np.array([...])
        a = a.args[0] if a.args else None
    if isinstance(a, (ast.List, ast.Tuple)) and len(a.elts) >= 2:
        x, y = num(a.elts[0]), num(a.elts[1])
        if x is not None and y is not None:
            return (x, y)
    return None


def layout_hints(code: str) -> list[str]:
    """布局体检（**不阻断**，只提建议）：找"很可能压在一起"的静态特征。

    能查的只有两类：写死的坐标撞车、过长的文本没缩放。
    真正的"高亮停错格子"这类语义问题查不出来 —— 那需要视觉模型。
    """
    hints: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return hints
    src_lines = (code or "").splitlines()

    # 1) 硬编码坐标撞车：同一时刻两个元素被放到几乎同一个点
    placed: list[tuple[float, float, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr in ("move_to",):
            c = _coord_of(node)
            if c:
                placed.append((c[0], c[1], getattr(node, "lineno", 0)))
    reported: set[int] = set()
    for i in range(len(placed)):
        if placed[i][2] in reported:
            continue
        for j in range(i + 1, len(placed)):
            x1, y1, l1 = placed[i]
            x2, y2, _ = placed[j]
            dist = ((x1 - x2) ** 2 + (y1 - y2) ** 2) ** 0.5
            if dist < 1.0 and l1 not in reported:
                reported.add(l1)
                hints.append(
                    f"第 {l1} 行与第 {placed[j][2]} 行的元素被放到几乎同一位置"
                    f"（相距 {dist:.2f}），画面可能重叠；"
                    "改用 to_edge / next_to(buff=0.4) / VGroup.arrange 让 manim 自己算间距")
                break
        if len(hints) >= 3:
            break

    # 2) 长文本未缩放：容易撑出画面或压住相邻元素
    long_text = 0
    for node in ast.walk(tree):
        if long_text >= 2:
            break
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
                and node.func.id in ("Text", "Paragraph", "MarkupText"):
            for s, lineno in _literal_strings(node):
                if len(s) < 24:
                    continue
                src = src_lines[lineno - 1] if 0 < lineno <= len(src_lines) else ""
                if "scale" in src or "font_size" in src:
                    continue
                hints.append(f"第 {lineno} 行的文本有 {len(s)} 个字且未缩放，"
                             "可能撑出画面压住其他元素；建议 .scale(0.6~0.75) 或手动分行")
                long_text += 1
                break
    return hints


# manim: Animation.run_time 的默认值（play 里不写就按这个算）
_PLAY_DEFAULT_RUN_TIME = 1.0

# 循环次数上限：range(1000) 之类的采样动画会把估算吹到荒谬的数字
_LOOP_CAP = 12


def _num(node):
    """取一个 AST 节点的数值；只认字面量（含负号），变量/表达式返回 None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        v = _num(node.operand)
        return -v if v is not None else None
    return None


def _kw_number(call: ast.Call, name: str):
    for kw in call.keywords:
        if kw.arg == name:
            return _num(kw.value)
    return None


def _call_attr(node) -> str:
    """self.play / self.wait 之类的调用名（只看 attr，够用且不吃 owner）。"""
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
        return node.func.attr
    return ""


def _run_time_of(call: ast.Call) -> tuple[float | None, bool]:
    """取一个 self.play(...) 的时长，返回 (秒数, 是否显式写过)。

    AI 有两种写法，都得认：
      self.play(Create(c), run_time=2)      <- run_time 挂在 play 上（优先）
      self.play(Create(c, run_time=2))      <- run_time 挂在动画对象自己身上，
                                               manim 同样认，取其中最大的那个
    """
    rt = _kw_number(call, "run_time")
    if rt is not None:
        return rt, True
    inner = []
    for node in ast.walk(call):
        if isinstance(node, ast.Call) and node is not call:
            v = _kw_number(node, "run_time")
            if v is not None:
                inner.append(v)
    if inner:
        return max(inner), True
    return None, False


def _loop_times(node: ast.For) -> int | None:
    """估算 for 的迭代次数：range 常量 / 字面列表才算得准，其余返回 None。"""
    it = node.iter
    if isinstance(it, (ast.List, ast.Tuple)):
        return len(it.elts)
    if isinstance(it, ast.Call) and getattr(it.func, "id", "") == "range":
        args = [_num(a) for a in it.args]
        if any(v is None for v in args):
            return None
        if len(args) == 1:
            return max(0, int(args[0]))
        if len(args) >= 2:
            start, stop = int(args[0]), int(args[1])
            step = int(args[2]) if len(args) > 2 and args[2] else 1
            if step == 0:
                return None
            return max(0, len(range(start, stop, step)))
    return None


def pacing_report(code: str) -> tuple[float, list[str]]:
    """节奏体检（**不阻断**，只提建议 + 一个估算秒数）。

    用户并不需要（也很难）自己填"视频要做多少秒"，节奏是交给 AI 的
    （提示词里写死了「中等偏慢」口径）。这个函数负责在**渲染之前**告诉用户
    AI 实际排出来大概多长，并对"偏快/没停留"的写法点名。

    估算口径（故意粗糙 —— 够判断快慢就行，不追求与 ffmpeg 一致）：
      self.play(...)  -> run_time，没写按 manim 默认 1.0 秒
      self.wait(x)    -> x 秒
      写在 for 里的    -> 按 range 次数乘算（封顶 _LOOP_CAP）
    """
    hints: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError:
        # 别假装"没提示" —— 那会让调用方以为脚本节奏没问题，其实压根没看进去
        return 0.0, ["脚本语法有误，跳过节奏估算"]

    total = 0.0
    plays = 0
    plays_no_rt = 0
    waits: list[float] = []
    uncertain = False

    def walk(node, mult: float):
        nonlocal total, plays, plays_no_rt, uncertain
        for child in ast.iter_child_nodes(node):
            m = mult
            if isinstance(child, ast.For):
                times = _loop_times(child)
                if times is None:
                    uncertain = True
                else:
                    m = mult * min(times, _LOOP_CAP)
            elif isinstance(child, ast.While):
                uncertain = True

            attr = _call_attr(child)
            if attr == "play":
                plays += 1
                rt, explicit = _run_time_of(child)
                if not explicit:
                    plays_no_rt += 1
                if rt is None:
                    rt = _PLAY_DEFAULT_RUN_TIME
                total += max(0.0, rt) * m
            elif attr == "wait":
                dur = None
                if child.args:
                    dur = _num(child.args[0])
                if dur is None:
                    dur = _kw_number(child, "duration")
                if dur is None:
                    dur = _PLAY_DEFAULT_RUN_TIME
                waits.append(dur)
                total += max(0.0, dur) * m

            walk(child, m)

    walk(tree, 1.0)

    if plays == 0:
        return round(total, 1), ["脚本里没找到 self.play(...)，跳过节奏估算"]

    if total < 25:
        hints.append(
            f"估算成片只有 {total:.0f} 秒，节奏偏快（目标 45~80 秒）："
            "给关键过程的 play 补 run_time=1.8~2.5，并在每个画面成形后补 self.wait(1.0~1.5)")
    elif total < 40:
        hints.append(
            f"估算成片约 {total:.0f} 秒，略快于「中等偏慢」的目标（45~80 秒），"
            "可在关键画面后多留 0.5~1 秒")
    elif total > 150:
        hints.append(
            f"估算成片约 {total:.0f} 秒，偏长：看看有没有重复循环或空转的 wait，"
            "确认是否需要拆成两支动画")

    if not waits:
        hints.append("整支动画一次 wait 都没有 —— 观众没有读画面的时间，务必补停留")
    else:
        mean = sum(waits) / len(waits)
        if mean < 0.6:
            hints.append(f"平均停留仅 {mean:.1f} 秒（共 {len(waits)} 次 wait），"
                         "关键画面建议提到 1.0~1.5 秒")
    if plays and plays_no_rt / plays >= 0.5:
        hints.append(f"{plays} 个 play 里有 {plays_no_rt} 个没写 run_time —— "
                     "节奏不受控（估算按 manim 默认 1 秒计）")
    if uncertain:
        hints.append("脚本里有静态推算不了的循环/分支，实际时长可能明显长于上面的估算")
    return round(total, 1), hints


def check(code: str, scene_name: str) -> tuple[bool, str]:
    """返回 (ok, 消息)。"""
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"语法错误：第 {e.lineno} 行：{e.msg}"

    classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    if scene_name not in classes:
        return False, f"未找到 Scene 类 {scene_name}（实际找到：{classes or '无'}）"

    forbidden = {"requests", "urllib", "socket", "subprocess", "shutil",
                 "multiprocessing", "ctypes", "pathlib"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root in forbidden:
                    return False, f"脚本使用了不允许的模块 import {alias.name}"
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in forbidden:
                return False, f"脚本使用了不允许的模块 from {node.module} import ..."

        # LaTeX 通道里混进中文 → pdflatex 必然报 Unicode character 错误。
        # 与其让它渲染 8 秒后失败，不如在此直接挡下并给出精确行号。
        elif isinstance(node, ast.Call) and _call_name(node) in _TEX_CLASSES:
            for s, lineno in _literal_strings(node):
                bad = sorted({ch for ch in s if ord(ch) > 127})
                if bad:
                    shown = "".join(bad[:6])
                    return False, (
                        f"第 {lineno} 行 {_call_name(node)} 中含有非 ASCII 字符（{shown}）："
                        "LaTeX 无法编译中文，该文案必须改用 "
                        'Text("...", font="Microsoft YaHei")；'
                        "注意 \\text{中文} 同样不合法，不要把中文留在 MathTex/Tex 里。"
                    )

    # 未定义名检查：渲染前抓 NameError（典型：from manim import * 但手写脚本漏了常量）
    defined, unknown_star = _collect_defined_names(tree)
    if not unknown_star:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
                if node.id not in defined and node.id not in _BUILTIN_NAMES:
                    return False, (
                        f"第 {node.lineno} 行使用了未定义的名称 {node.id}："
                        "运行时会 NameError。多半是漏了 import（manim 的常量如 RIGHT/ORIGIN/WHITE "
                        "在 from manim import * 之后才可用）或变量名拼写错误。"
                    )
    return True, "静态检查通过"
