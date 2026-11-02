@echo off
rem MathViz launcher.
rem   double-click   -> MathViz.exe（原生启动器，GUI 子系统，不弹黑窗）
rem                    它不在时退回 wscript + MathViz.vbs（效果相同，纯脚本）
rem   run.bat debug  -> keep the console, useful when something crashes
rem   run.bat feedback -> 反馈台（作者看收到的反馈），不进主界面

if /i "%~1"=="debug" goto :debug
if /i "%~1"=="feedback" goto :feedback

rem 优先用编译好的启动器：没有 cmd 闪窗，还带图标
if exist "%~dp0MathViz.exe" (
    start "" "%~dp0MathViz.exe"
    exit /b
)

rem 兜底：启动器被删 / 被杀软隔离时，直接走脚本
start "" wscript.exe //nologo "%~dp0MathViz.vbs"
exit /b

:debug
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.main
if errorlevel 1 pause
exit /b

:feedback
cd /d "%~dp0"
start "" ".venv\Scripts\pythonw.exe" -m app.main --feedback-inbox
exit /b
