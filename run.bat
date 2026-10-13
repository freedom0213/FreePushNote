@echo off
rem FreePushNote launcher. Double click this file, or run it from a shell.
rem Starts the app with pythonw so no console window stays open.
rem
rem KEEP THIS FILE PURE ASCII (English only) AND USE CRLF LINE ENDINGS.
rem cmd.exe reads a .bat byte by byte using the console codepage. Non-ASCII
rem comments get garbled on a GBK console, and the leftovers are then executed
rem as commands ("xxx is not recognized as an internal or external command").
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
