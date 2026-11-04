"""检查更新与程序内升级。

数据源是 GitHub Releases 的 `latest` 接口 —— 附件地址、说明、版本号都是结构化字段，
比抓网页稳。三个容易踩的坑在这里一次性处理掉：

1. **版本不能比字符串**："1.10.0" < "1.9.0" 会判错，必须按数字分段比；
2. **本机的 http_proxy 可能是个死代理**（连不上、502、拒绝连接），
   请求失败后自动改直连重试一次 —— 浏览器直连能开 GitHub，这里就也能；
3. **安装包要提权**：Inno 的 setup 带 requireAdministrator 清单，
   CreateProcess 对它直接报 740，只能经 ShellExecute（cmd 的 start）自动弹 UAC。

本模块只依赖标准库，不碰 Qt —— 界面在 app/ui/update_dialog.py。
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import config

OWNER = "China-rock"
REPO = "mathviz"
API_LATEST = f"https://api.github.com/repos/{OWNER}/{REPO}/releases/latest"
RELEASE_PAGE = f"https://github.com/{OWNER}/{REPO}/releases/latest"
USER_AGENT = f"MathViz/{config.APP_VERSION} (+https://github.com/{OWNER}/{REPO})"

CHUNK = 1 << 18          # 256 KB，进度更新够密又不至于刷爆事件循环
CHECK_TIMEOUT = 12
READ_TIMEOUT = 30


class UpdateError(Exception):
    """检查/下载失败。message 直接拿去显示，已经是人话。"""


class UpdateCancelled(Exception):
    """用户中途点了取消。"""


# ---------- 版本与附件（纯逻辑，好测）

def parse_version(text) -> tuple:
    """'v1.1.0' / '1.1' / 'MathViz 1.1.0-beta' → (1, 1, 0)。取不到数字就是 (0,)。"""
    nums = re.findall(r"\d+", str(text or ""))
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def is_newer(remote, current) -> bool:
    """remote 是否比 current 新。按段比数字，缺的段补 0（1.1 == 1.1.0）。"""
    a, b = parse_version(remote), parse_version(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def pick_installer(assets) -> dict | None:
    """从 release 附件里挑 Windows 安装包。

    优先级：名字带 setup 的 > 名字带 mathviz 的 > 体积大的。
    挑不到就返回 None（比如这次的 release 只传了源码包）。
    """
    exes = [a for a in (assets or [])
            if str(a.get("name", "")).lower().endswith(".exe")
            and (a.get("browser_download_url") or a.get("url"))]
    if not exes:
        return None

    def score(a):
        name = str(a.get("name", "")).lower()
        return ("setup" in name, "mathviz" in name, int(a.get("size") or 0))

    best = max(exes, key=score)
    return {
        "name": best.get("name", "MathViz-Setup.exe"),
        "url": best.get("browser_download_url") or best.get("url"),
        "size": int(best.get("size") or 0),
    }


def summarize_notes(body: str, limit: int = 4000) -> str:
    """Release 说明截断（正常几 KB，防有人贴一整篇）。"""
    text = (body or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n\n……（说明太长，完整内容见发布页）"


def human_size(n: int) -> str:
    if n <= 0:
        return "大小未知"
    if n < 1024 * 1024:
        return f"{n / 1024:.0f} KB"
    return f"{n / 1048576:.0f} MB"


# ---------- 网络

def _open(url: str, use_proxy: bool, timeout: int):
    handlers = []
    if not use_proxy:
        # 空 ProxyHandler = 谁都不走代理
        handlers.append(urllib.request.ProxyHandler({}))
    opener = urllib.request.build_opener(*handlers)
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.github+json",
    })
    return opener.open(req, timeout=timeout)


def _with_fallback(fn):
    """先按系统代理试，失败再直连试一次。

    只有"网络层"的失败才重试 —— HTTP 403/404 换了直连也一样，直接报错更省时间。
    """
    last = None
    for use_proxy in (True, False):
        try:
            return fn(use_proxy)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise UpdateError(
                    "发布页不存在（404）—— 仓库地址可能变了") from e
            if e.code in (403, 429):
                raise UpdateError(
                    "GitHub 接口限流了（403）—— 过一会儿再试，"
                    "或在浏览器直接打开发布页") from e
            last = e
        except Exception as e:      # 超时 / DNS / 代理拒绝 / SSL
            last = e
        # 到这里：要么是网络层故障，要么是 5xx —— 都值得换直连再试一次
    raise UpdateError(
        f"连不上 GitHub（{last}）—— 网络或代理问题，可先打开发布页手动下载")


def fetch_latest() -> dict:
    """读 latest release。返回扁平化的 dict，界面直接拿字段用。

    没发过 release 时 GitHub 返 404，也归到 UpdateError 里，不算崩溃。
    """
    def go(use_proxy):
        with _open(API_LATEST, use_proxy, CHECK_TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))

    data = _with_fallback(go)
    if not isinstance(data, dict) or not data.get("tag_name"):
        raise UpdateError("发布信息格式不对（接口返回了意料之外的内容）")

    tag = str(data.get("tag_name", "")).strip()
    installer = pick_installer(data.get("assets"))
    return {
        "version": tag,
        "name": (data.get("name") or tag).strip(),
        "notes": summarize_notes(data.get("body", "")),
        "page": data.get("html_url") or RELEASE_PAGE,
        "published": str(data.get("published_at") or "")[:10],
        "installer": installer,
        "prerelease": bool(data.get("prerelease")),
    }


def download_dir() -> Path:
    """安装包下载目录（用户数据目录下，卸载/清缓存时容易找）。"""
    d = Path(config.DATA_DIR) / "updates"
    d.mkdir(parents=True, exist_ok=True)
    return d


def download(url: str, dest: Path, progress=None, cancelled=None) -> Path:
    """流式下载到 dest。progress(已收字节, 总字节)，总字节未知时为 0。

    先写 .part 再改名：中途失败/取消不会留下一个看起来完整的坏安装包。
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")

    def go(use_proxy):
        with _open(url, use_proxy, READ_TIMEOUT) as r, open(part, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            got = 0
            while True:
                if cancelled is not None and cancelled():
                    raise UpdateCancelled()
                chunk = r.read(CHUNK)
                if not chunk:
                    break
                f.write(chunk)
                got += len(chunk)
                if progress is not None:
                    progress(got, total)
            return got

    try:
        size = _with_fallback(go)
    except UpdateCancelled:
        part.unlink(missing_ok=True)
        raise
    except UpdateError:
        part.unlink(missing_ok=True)
        raise
    except Exception as e:
        part.unlink(missing_ok=True)
        raise UpdateError(f"下载失败：{e}") from e

    if size <= 0:
        part.unlink(missing_ok=True)
        raise UpdateError("下载到的文件是空的，请重试")
    part.replace(dest)
    return dest


# ---------- 安装

def can_self_update() -> bool:
    """源码运行时不接管安装：没有安装目录、也不该替用户决定装哪。"""
    return bool(config.IS_FROZEN) and sys.platform == "win32"


def _cmd_path() -> Path:
    return Path(tempfile.gettempdir()) / "mathviz_update.cmd"


def build_install_script(setup: Path, delay: int = 3) -> str:
    """生成"等本程序退干净 → 静默装 → 自动重启"的批处理。

    delay 秒是给 Qt 窗口、日志线程、渲染子进程留的退出余量 ——
    少这个延迟，安装包可能撞上正在被占用的 exe 而提示"请关闭程序"。
    """
    lines = [
        "@echo off",
        f"ping -n {int(delay) + 1} 127.0.0.1 >nul",
        f'start "" "{setup}" /SILENT /CLOSEAPPLICATIONS /NORESTART',
    ]
    return "\r\n".join(lines) + "\r\n"


def launch_installer(setup: Path, delay: int = 3) -> Path:
    """启动安装脚本，调用方随后应立即退出程序。

    cmd 的 `start` 走 ShellExecute，安装包的 requireAdministrator 清单
    会正常触发 UAC；直接 CreateProcess 会失败（WinError 740）。
    CREATE_NO_WINDOW 是为了不闪黑窗口。
    """
    setup = Path(setup)
    if not setup.exists():
        raise UpdateError(f"安装包不见了：{setup}")
    script = _cmd_path()
    encoding = "mbcs" if os.name == "nt" else "utf-8"
    script.write_text(build_install_script(setup, delay), encoding=encoding)
    flags = 0x08000000 if os.name == "nt" else 0   # CREATE_NO_WINDOW
    subprocess.Popen(["cmd.exe", "/c", str(script)],
                     creationflags=flags, close_fds=True)
    return script


# ---------- 自动检查的节流

AUTO_CHECK_INTERVAL = 6 * 3600      # 启动后多久内不重复查（GitHub 匿名限流 60 次/小时）


def should_auto_check(last_check_ts: float, now: float | None = None,
                      interval: int = AUTO_CHECK_INTERVAL) -> bool:
    """启动时的静默检查要不要跑：距上次不足 interval 就跳过。"""
    now = time.time() if now is None else now
    try:
        last = float(last_check_ts or 0)
    except (TypeError, ValueError):
        return True
    if last <= 0 or last > now:      # 从没查过，或时钟被改过
        return True
    return (now - last) >= interval
