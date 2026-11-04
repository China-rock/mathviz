"""检查更新 / 程序内升级（offscreen，不联网）。"""
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJ = str(Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJ)

from PySide6.QtWidgets import QApplication  # noqa: E402

from app.core import config, updater  # noqa: E402
from app.ui.update_dialog import UpdateDialog  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

ok = []
app = QApplication([])

# ---------- 1) 版本解析与比较的边界 ----------
assert updater.parse_version("v1.1.0") == (1, 1, 0)
assert updater.parse_version("MathViz 1.10.2-beta") == (1, 10, 2)
assert updater.parse_version("") == (0,)
assert updater.is_newer("v1.10.0", "1.9.9")          # 字符串比会判错的那类
assert not updater.is_newer("v1.1", "1.1.0")          # 缺段补 0，不算新版
assert not updater.is_newer("1.0.0", "1.0.0")
assert updater.is_newer("2.0", "1.9.9")
ok.append("版本解析/比较（v 前缀、补零、跨位进位）")

# ---------- 2) 附件挑选：认 setup、认 mathviz、认体积 ----------
inst = updater.pick_installer([
    {"name": "MathViz-1.1.0-Setup.exe", "browser_download_url": "http://a", "size": 10},
    {"name": "portable.exe", "browser_download_url": "http://b", "size": 999},
    {"name": "source.zip", "url": "http://c", "size": 500},
])
assert inst and inst["name"] == "MathViz-1.1.0-Setup.exe" and inst["url"] == "http://a"
assert updater.pick_installer([{"name": "readme.txt", "url": "x"}]) is None
assert updater.pick_installer([]) is None
assert updater.pick_installer(None) is None
ok.append("安装包附件挑选（setup 优先 / 无 exe 返 None）")

# ---------- 3) 说明截断与大小显示 ----------
long_notes = "x" * 5000
assert len(updater.summarize_notes(long_notes)) < 5000
assert "发布页" in updater.summarize_notes(long_notes)
assert updater.summarize_notes("短说明") == "短说明"
assert updater.summarize_notes(None) == ""
assert updater.human_size(231 * 1048576).endswith("MB")
assert updater.human_size(800).endswith("KB")
ok.append("说明截断 / 体积格式化")

# ---------- 4) 自动检查的节流 ----------
assert updater.should_auto_check(0)                    # 从没查过 → 查
assert updater.should_auto_check("bad")                # 脏数据 → 查
now = 1_000_000.0
assert not updater.should_auto_check(now, now=now + 60)          # 一小时前查过 → 跳
assert updater.should_auto_check(now, now=now + 7 * 3600)        # 超 6 小时 → 查
assert updater.should_auto_check(now + 999, now=now)             # 时钟倒退 → 查
ok.append("启动静默检查的 6 小时节流（含脏数据/时钟倒退）")

# ---------- 5) 安装脚本内容（延迟 + 静默参数 + 引号路径） ----------
s = updater.build_install_script(r"C:\a b\Setup 1.1.exe", delay=3)
assert "ping -n 4 127.0.0.1 >nul" in s
assert 'start "" "C:\\a b\\Setup 1.1.exe" /SILENT /CLOSEAPPLICATIONS' in s
assert s.endswith("\r\n")
ok.append("安装批处理：延迟启动 + 静默参数 + 带空格路径")

# ---------- 6) 下载目录与自更新判定 ----------
d = updater.download_dir()
assert d.name == "updates" and d.is_dir()
assert str(d) == str(Path(config.DATA_DIR) / "updates")
assert updater.can_self_update() is False             # 源码运行：不接管安装
ok.append("下载目录落在用户数据目录；源码运行不自动安装")

# ---------- 7) 对话框：正常信息 + 无附件时的禁用 ----------
INFO = {"version": "v1.1.0", "name": "MathViz v1.1.0", "published": "2026-11-04",
        "page": "http://page", "notes": "## 更新\n- 一", "prerelease": False,
        "installer": {"name": "MathViz-1.1.0-Setup.exe", "url": "http://a",
                      "size": 231 * 1048576}}
dlg = UpdateDialog(INFO)
assert "v1.1.0" in dlg.windowTitle()
assert not dlg.btn_go.isEnabled()                     # 源码运行：不接管安装，只给发布页
assert not dlg.bar.isVisible()                        # 初始没有进度条
ok.append("更新对话框：标题/按钮初始状态")

INFO2 = dict(INFO, installer=None)
dlg2 = UpdateDialog(INFO2)
assert not dlg2.btn_go.isEnabled()
assert "没有附带安装包" in dlg2.lbl_status.text()
ok.append("release 没传安装包时禁用「立即更新」并给指引")

# ---------- 8) 主窗口集成：菜单动作存在、文案随状态走 ----------
w = MainWindow()
w.show()
app.processEvents()
assert w.act_update is not None and w.act_update.isEnabled()
assert "检查更新" in w.act_update.text()
w._mark_update_available("v1.2.0")
assert "v1.2.0" in w.act_update.text()
w._update_available = ""
w._refresh_update_action()
assert "检查更新" in w.act_update.text() and "v1.2.0" not in w.act_update.text()
ok.append("主窗口菜单项存在，发现新版后文案带版本号")

# ---------- 9) 帮助菜单里确实挂上了这个动作（找得到才点得到） ----------
menu = None
for a in w.menuBar().actions():
    if "帮助" in a.text():
        menu = a.menu()
        break
assert menu is not None
texts = [act.text() for act in menu.actions()]
assert any("检查更新" in t for t in texts), texts
ok.append("帮助菜单挂了「检查更新」")

# ---------- 10) 关于框文本含版本号 ----------
assert config.APP_VERSION in w._about_text()
ok.append("关于框显示版本号")

print("\n".join("  ✓ " + s for s in ok))
print(f"\n检查更新：{len(ok)} 项通过")
