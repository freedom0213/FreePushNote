@echo off
rem FreePushNote 启动入口（双击即可）。用 pythonw 启动，不弹控制台窗口。
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo [FreePushNote] virtual environment not found.
    echo.
    echo Please run once:
    echo     python -m venv .venv
    echo     .venv\Scripts\python.exe -m pip install PySide6
    echo.
    pause
    exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "app\main.py"
