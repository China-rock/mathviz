"""manim 渲染子进程入口 —— 只在打包产物里用到。

为什么需要它：打包成 exe 之后解释器被冻结，`MathViz.exe -m manim ...` 不会再
去跑 manim（它只会正常弹出界面，然后渲染静默失败）。所以渲染必须交给一个独立
的可执行文件来承担。本文件就是那个入口，命令行参数与 `python -m manim` 完全
一致，主程序在 sys.frozen 时改成调用同目录的 manim_worker.exe。

开发环境下不会用到它（renderer 走 `python -m manim`），它只是 PyInstaller 的
第二个 Analysis 输入，通过 MERGE 与主程序共用一份依赖，不会让体积翻倍。
"""

from __future__ import annotations

import sys


def main() -> int:
    # 延迟导入：manim 启动时会读配置、初始化 OpenGL 后端，
    # 放在函数里可以避免打包分析期之外的副作用。
    from manim.__main__ import main as manim_main

    manim_main()  # click/cloup 会自己解析 sys.argv 并在结束时 SystemExit
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise          # manim 自己抛的退出码，原样传出去
    except Exception:   # 兜底：任何异常都要留下痕迹，别让主程序只看到空输出
        import traceback

        traceback.print_exc()
        sys.exit(1)
