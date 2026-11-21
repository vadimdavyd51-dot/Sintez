@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONUTF8=1
set HF_HOME=%~dp0models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1
set HF_HUB_OFFLINE=1
if not exist python\python.exe (
    echo Не найден python\python.exe: программа установлена не полностью.
    pause
    exit /b 1
)
python\python.exe app.py
pause
