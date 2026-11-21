@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set HF_HOME=%~dp0models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
if not exist venv\Scripts\python.exe (
    echo Сначала запусти install.bat
    pause
    exit /b 1
)
venv\Scripts\python.exe app.py
pause
