@echo off
rem MathViz：便携目录 -> 单个安装包
rem
rem 前置两步：
rem   1) .venv\Scripts\python.exe packaging\build_all.py      产出 dist\MathViz
rem   2) 安装 Inno Setup 6（https://jrsoftware.org/isdl.php）
rem
rem 然后双击本文件，产出 dist\MathViz-1.0-Setup.exe

setlocal
set ISCC="C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist %ISCC% set ISCC="C:\Program Files\Inno Setup 6\ISCC.exe"
if not exist %ISCC% (
    echo 没找到 Inno Setup。请到 https://jrsoftware.org/isdl.php 下载安装后重试。
    pause
    exit /b 1
)

cd /d "%~dp0.."
if not exist "dist\MathViz\MathViz.exe" (
    echo 先跑 packaging\build_all.py 产出便携目录，再来打安装包。
    pause
    exit /b 1
)

%ISCC% packaging\installer.iss
if errorlevel 1 (
    echo 编译失败。
    pause
    exit /b 1
)
echo 完成：dist\MathViz-1.0-Setup.exe
pause
