"""渲染预检测：体检要挡得住必然失败的脚本，也要放行正常的脚本（offscreen）"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PROJ = str(__import__("pathlib").Path(__file__).resolve().parents[1])
sys.path.insert(0, PROJ)

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

# 弹窗里"用户点哪个"由这里决定：预检测在 offscreen 下不能真弹窗等着点
CHOICE = {"force": False}


def _fake_exec(self, *a):
    return 0


def _fake_clicked(self, *a):
    want = (QMessageBox.ButtonRole.AcceptRole if CHOICE["force"]
            else QMessageBox.ButtonRole.RejectRole)
    for b in self.buttons():
        if self.buttonRole(b) == want:
            return b
    return None


QMessageBox.exec = _fake_exec
QMessageBox.clickedButton = _fake_clicked

from app.core import renderer, validator  # noqa: E402
from app.ui.main_window import MainWindow  # noqa: E402

ok = []

# ---------- 1) 场景类探测（预检测自救的底层口径） ----------
GOOD = '''from manim import *

class Demo(Scene):
    def construct(self):
        self.play(Write(Text("你好")))
'''
assert renderer.scene_class_names(GOOD) == ["Demo"], renderer.scene_class_names(GOOD)
assert renderer.scene_class_names("class T:\n    pass\n") == [], "非 Scene 子类不算"
assert renderer.scene_class_names("def f(:\n") == [], "语法错要返回空表而不是抛异常"
ok.append("scene_class_names 只认 Scene/ThreeDScene 子类")

app = QApplication([])
w = MainWindow()
w.show()
app.processEvents()

# ---------- 2) 正常脚本：放行 ----------
w.editor.setPlainText(GOOD)
w.current_scene_name = "Demo"
assert w._precheck(GOOD, "渲染") is True, "好脚本不该被拦"
ok.append("正常脚本预检测放行")

# ---------- 3) 场景名对不上：自动改用脚本里的类 ----------
w.editor.setPlainText(GOOD)
w.current_scene_name = "KP0101_000000"
assert w._precheck(GOOD, "渲染") is True, "只有一个 Scene 类时应自救而不是拦下"
assert w.current_scene_name == "Demo", w.current_scene_name
assert "Demo" in w.lbl_scene.text(), w.lbl_scene.text()
ok.append("场景名对不上时自动改用脚本里的类")

# ---------- 4) MathTex 里混中文：必然失败，要挡 ----------
CN_IN_TEX = '''from manim import *

class Demo(Scene):
    def construct(self):
        self.play(Write(MathTex("速度 v")))
'''
w.editor.setPlainText(CN_IN_TEX)
w.current_scene_name = "Demo"
CHOICE["force"] = False
assert w._precheck(CN_IN_TEX, "渲染") is False, "MathTex 里的中文必须挡下"
CHOICE["force"] = True
assert w._precheck(CN_IN_TEX, "渲染") is True, "强行继续要能放行"
ok.append("MathTex 混中文：挡住 + 允许强行继续")

# ---------- 5) 语法错 / 未定义名 / 无 Scene 类 ----------
BAD_SYNTAX = "class Demo(Scene):\n    def construct(self)\n        self.play()\n"
w.editor.setPlainText(BAD_SYNTAX)
CHOICE["force"] = False
assert w._precheck(BAD_SYNTAX, "渲染") is False, "语法错要挡"
ok.append("语法错挡下")

UNDEF = '''from manim import *

class Demo(Scene):
    def construct(self):
        self.play(Write(NotDefinedAnywhere))
'''
w.editor.setPlainText(UNDEF)
assert w._precheck(UNDEF, "渲染") is False, "未定义名要挡"
ok.append("未定义名挡下")

TWO_SCENES = '''from manim import *

class A(Scene):
    def construct(self):
        self.wait(1)

class B(Scene):
    def construct(self):
        self.wait(1)
'''
w.editor.setPlainText(TWO_SCENES)
w.current_scene_name = "KP0101_000000"
assert w._precheck(TWO_SCENES, "渲染") is False, "两个 Scene 类无法确定入口，要挡"
ok.append("多个 Scene 类不擅自改名（交给人决定）")

# ---------- 6) 快检入口同样走预检测 ----------
w.editor.setPlainText(CN_IN_TEX)
w.current_scene_name = "Demo"
CHOICE["force"] = False
assert w._precheck(CN_IN_TEX, "快检") is False, "快检也要过体检"
ok.append("快检入口同样体检")

# ---------- 7) 菜单动作存在且跟着"有没有脚本"变 ----------
assert hasattr(w, "act_precheck"), "菜单里要有预检测动作"
w.editor.setPlainText("")
w._refresh_buttons()
assert not w.act_precheck.isEnabled(), "空编辑器时预检测应禁用"
w.editor.setPlainText(GOOD)
w._refresh_buttons()
assert w.act_precheck.isEnabled(), "有脚本时预检测应可用"
assert w.act_precheck.text().startswith("🔍"), w.act_precheck.text()
ok.append("预检测菜单动作随脚本有无启用")

# ---------- 8) 体检结果写进日志 ----------
w.editor.setPlainText(GOOD)
w.current_scene_name = "Demo"
w.log_view.clear()
assert w._precheck(GOOD, "渲染") is True
assert "[预检]" in w.log_view.toPlainText(), w.log_view.toPlainText()[-200:]
ok.append("预检测结论进日志")

print("\n".join("  ✓ " + s for s in ok))
print(f"\n预检测：{len(ok)} 项通过")
