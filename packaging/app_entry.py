"""打包用的主程序入口。

直接拿 app/main.py 当 PyInstaller 脚本也能跑，但那样 `app` 包既作为脚本模块
又作为包被两套路径引用，日志目录推算容易出岔子。这里用一行调用把它接进来，
行为与 `python -m app.main` 完全一致。
"""

from app.main import main

if __name__ == "__main__":
    main()
