"""全局配置：API Key 解析、路径规划。

Key 的查找顺序：
  1. 环境变量（默认 DEEPSEEK_API_KEY / DEEPSEEK_APIKEY / DEEPSEEK_KEY）
  2. .env 文件里的同名键

若你的 Key 存放在一个自定义名字的环境变量里，在 .env 中写一行
`DEEPSEEK_API_KEY_ENV_NAME=你的变量名` 即可（.env 不入库，不会泄漏名字）。
"""
import os
import sys
import tempfile
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)   # True = 运行在打包出来的 exe 里


def _app_dir() -> Path:
    """程序资源目录（只读）：图标、内置素材、README。

    打包后代码在 _internal 里（onefile 则是临时解包目录），不是项目根目录了，
    所以不能再用 __file__ 往上推两级。
    """
    if IS_FROZEN:
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parents[2]


APP_DIR = _app_dir()
PROJECT_ROOT = APP_DIR          # 旧名字保留：现在指"只读资源根"，别再往里写东西


def _data_dir() -> Path:
    """可写数据目录：API Key、成片、日志、缓存、版本快照。

    打包后程序目录很可能是只读的（装到 Program Files），往里写会直接 PermissionError，
    所以这些一律落到用户目录；开发时仍是项目根，行为与以前完全一致。
    """
    override = os.environ.get("MATHVIZ_USER_DIR")
    if override:
        return Path(override)
    if IS_FROZEN:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        else:
            base = str(Path.home())
        return Path(base) / "MathViz"
    return Path(__file__).resolve().parents[2]


DATA_DIR = _data_dir()

# 版本号：安装包（packaging/installer.iss 的 MyAppVersion）与反馈码里的记录都用它，
# 改版本时两处一起改，否则你收到的反馈会写着旧版本号。
APP_VERSION = "1.0.0"

# .env 可能两份都有（开发时同源、打包后用户目录优先），逐个找
ENV_FILE = DATA_DIR / ".env"
ENV_FILE_FALLBACK = APP_DIR / ".env"

ICON_FILE = APP_DIR / "assets" / "mathviz-icon-v2.ico"
SCENES_DIR = DATA_DIR / "scenes"
OUTPUT_MEDIA_DIR = DATA_DIR / "media"                # 成片归档（用户目录）


def default_work_dir() -> Path:
    """渲染工作目录：必须无空格、无中文（LaTeX 在带空格路径下会闹脾气）。

    优先级：环境变量 MATHVIZ_WORK_DIR > 系统本地目录 > 临时目录。
    Windows 用 %LOCALAPPDATA%（形如 C:\\Users\\xxx\\AppData\\Local，天然无空格）。
    """
    override = os.environ.get("MATHVIZ_WORK_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        return Path(base) / "MathVizWork"
    return Path(tempfile.gettempdir()) / "MathVizWork"


# 渲染工作目录（渲染时的 cwd 与中间产物，不入库）
RENDER_WORK_DIR = default_work_dir()
RENDER_MEDIA_DIR = RENDER_WORK_DIR / "media"

DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEEPSEEK_MODEL = "deepseek-chat"

# 默认查找的环境变量名；可通过 .env 里的 DEEPSEEK_API_KEY_ENV_NAME 追加自定义名字
DEFAULT_API_KEY_VAR_NAMES = ("DEEPSEEK_API_KEY", "DEEPSEEK_APIKEY", "DEEPSEEK_KEY")

# 指向"真正存放 Key 的环境变量名"的间接配置键（写在 .env 中）
API_KEY_ENV_NAME_KEY = "DEEPSEEK_API_KEY_ENV_NAME"


def api_key_var_names() -> tuple[str, ...]:
    """自定义变量名（来自 .env 或环境变量）优先，其后是默认名。"""
    extra = os.environ.get(API_KEY_ENV_NAME_KEY) or load_env_file().get(API_KEY_ENV_NAME_KEY)
    names: list[str] = []
    if extra:
        for n in extra.replace(",", " ").split():
            if n and n not in names:
                names.append(n)
    for n in DEFAULT_API_KEY_VAR_NAMES:
        if n not in names:
            names.append(n)
    return tuple(names)

# 课件文本过长时截断，避免 token 爆炸
MAX_COURSETEXT_CHARS = 60000

# 课件文件大小门槛（AI 上下文有限：超大文件通常意味着整本书而非一节课，
# 即便文本截断，解析耗时和提取质量也会崩坏，不如一开始就拒收并提示拆分）
MAX_FILE_SIZE_MB = 20

# ── 大文件的"体脂率"判定 ───────────────────────────────────────────────
# PPT/DOCX 常因为高清图片、视频而虚胖到几百 MB，但文本可能只有几 KB。
# 这类文件的媒体部分在解析时是被惰性跳过的（实测 448MB PPT 提取文本仅 2.3s），
# 若按总大小一刀切会误杀大量正常课件。因此：
#   ① 用 zip 目录表算出"媒体 vs 文本"的体脂率（不读内容，毫秒级）
#   ② 只有"文本部分"本身超限才拒收，媒体再大也放行
MAX_CONTENT_TEXT_MB = 8      # 结构化文档里非媒体部分的体积上限
MAX_FILE_SIZE_MB_HARD = 1024  # 绝对上限（1 GB），超过一律拒收，防病态文件

# 支持的课件格式（与界面提示、文件对话框保持一致）
COURSE_EXTENSIONS = (".pdf", ".pptx", ".docx", ".md", ".txt", ".tex")


def _strip_inline_comment(val: str) -> str:
    """去掉行尾注释：`sk-xxx  # 我的 key` -> `sk-xxx`。

    只认"引号外、且 # 前面有空白"的注释 —— 否则值里本来带的 # （密码常见）
    会被误当注释砍掉。手工编辑 .env 加注是再自然不过的动作，原来会把整段注释
    连进 Key 里，界面显示"已配置"但请求一律 401，用户根本查不出来。
    """
    out: list[str] = []
    quote = ""
    for i, ch in enumerate(val):
        if quote:
            out.append(ch)
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
            out.append(ch)
        elif ch == "#" and (i == 0 or val[i - 1] in " \t"):
            break
        else:
            out.append(ch)
    return "".join(out).strip()


def load_env_file() -> dict:
    """极简 .env 解析，不引入额外依赖。

    用户目录那份优先（打包后程序目录可能是只读的，Key 只能写在用户目录）；
    两份同名键以先读到的为准。
    """
    result = {}
    for path in (ENV_FILE, ENV_FILE_FALLBACK):
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            val = _strip_inline_comment(val)
            result.setdefault(key.strip(), val.strip('"').strip("'"))
    return result


def save_api_key(key: str) -> Path:
    """把 Key 写进用户目录的 .env（首次启动向导用）。

    打过包之后没有项目根目录可写，也没法替用户设环境变量，只能落到
    %LOCALAPPDATA%\\MathViz\\.env —— 那里不入库、不随卸载残留到别人的机器上。
    文件里已有的其它配置会保留，只覆盖 DEEPSEEK_API_KEY 这一行。
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    if ENV_FILE.exists():
        lines = ENV_FILE.read_text(encoding="utf-8", errors="ignore").splitlines()
    kept = [ln for ln in lines
            if not ln.strip().startswith("DEEPSEEK_API_KEY=")]
    kept.append(f"DEEPSEEK_API_KEY={key.strip()}")
    ENV_FILE.write_text("\n".join(kept) + "\n", encoding="utf-8")
    return ENV_FILE


def get_api_key() -> str | None:
    env_file = load_env_file()
    for name in api_key_var_names():
        val = os.environ.get(name)
        if val and val.strip():
            return val.strip()
    for name in api_key_var_names():
        val = env_file.get(name)
        if val and val.strip():
            return val.strip()
    return None


def api_key_source() -> str:
    """返回 Key 的来源描述，用于界面显示。"""
    env_file = load_env_file()
    for name in api_key_var_names():
        if os.environ.get(name, "").strip():
            return f"环境变量 {name}"
    for name in api_key_var_names():
        if env_file.get(name, "").strip():
            return f".env 文件（{name}）"
    return "未找到"


def ensure_dirs():
    # 缓存目录在这里一并建好（不 import cache 模块，避免循环依赖）
    cache_dir = DATA_DIR / "cache"
    for d in (SCENES_DIR, OUTPUT_MEDIA_DIR, RENDER_WORK_DIR, RENDER_MEDIA_DIR,
              cache_dir):
        d.mkdir(parents=True, exist_ok=True)
