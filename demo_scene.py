"""环境验收测试场景：坐标轴 + 正弦曲线 + MathTex 公式。
用于验证 manim + ffmpeg + LaTeX 全链路。"""
from manim import *
import numpy as np


class DemoScene(Scene):
    def construct(self):
        axes = Axes(
            x_range=[-PI, PI, PI / 2],
            y_range=[-1.5, 1.5, 1],
            x_length=10,
            y_length=4,
            axis_config={"include_tip": False},
        )
        graph = axes.plot(lambda x: np.sin(x), x_range=[-PI, PI], color=YELLOW)
        label = MathTex(r"y = \sin x", font_size=60).next_to(axes, UP)
        title = Text("环境验收测试：MathTex + 中文", font="Microsoft YaHei",
                     font_size=28).to_edge(UP)

        x = ValueTracker(-PI)
        dot = Dot(color=RED)
        dot.add_updater(lambda m: m.move_to(
            axes.c2p(x.get_value(), np.sin(x.get_value()))))

        self.play(Create(axes))
        self.play(Create(graph), Write(label), FadeIn(title))
        self.add(dot)
        self.play(x.animate.set_value(PI), run_time=3, rate_func=linear)
        dot.clear_updaters()
        self.wait(1)
