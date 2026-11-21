@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
set PYTHONUTF8=1
set HF_HOME=%~dp0models
set HF_HUB_DISABLE_SYMLINKS_WARNING=1

echo ============================================
echo   Установка «Рассказчика»: 15-30 минут, нужен интернет
echo   Окно не закрывай, пока не появится «Готово»
echo ============================================
echo.

set "PYEXE="
if exist "%~dp0python\python.exe" set "PYEXE=%~dp0python\python.exe"
if defined PYEXE goto have_python
py -3.11 --version >nul 2>nul
if not errorlevel 1 set "PYEXE=py -3.11"
if defined PYEXE goto have_python

echo [0/4] Скачиваю и ставлю Python 3.11 (только для этой программы)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "[Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe -OutFile '%~dp0python-setup.exe'"
if not exist "%~dp0python-setup.exe" goto err_python
"%~dp0python-setup.exe" /quiet InstallAllUsers=0 TargetDir="%~dp0python" Include_launcher=0 Include_test=0 PrependPath=0 Shortcuts=0 Include_doc=0
del "%~dp0python-setup.exe" >nul 2>nul
if not exist "%~dp0python\python.exe" goto err_python
set "PYEXE=%~dp0python\python.exe"

:have_python
echo Python: %PYEXE%
if exist venv\Scripts\python.exe goto have_venv
%PYEXE% -m venv venv
if errorlevel 1 goto err_venv

:have_venv
set "PY=venv\Scripts\python.exe"
%PY% -m pip install --upgrade pip

echo.
echo [1/4] PyTorch для видеокарты NVIDIA...
%PY% -m pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu124
if errorlevel 1 goto err_pip

echo.
echo [2/4] Библиотеки озвучки...
%PY% -m pip install f5-tts ruaccent
if errorlevel 1 goto err_pip
%PY% -m pip uninstall -y torchvision >nul 2>nul

%PY% -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"
if not errorlevel 1 goto gpu_ok
echo Видеокарта пока не видна. Переставляю PyTorch с поддержкой NVIDIA...
%PY% -m pip install --force-reinstall --no-deps torch torchaudio --index-url https://download.pytorch.org/whl/cu124
%PY% -c "import torch,sys; sys.exit(0 if torch.cuda.is_available() else 1)"
if errorlevel 1 goto err_gpu

:gpu_ok
echo.
echo [3/4] Скачиваю модели (несколько гигабайт, терпение)...
%PY% engine.py --preload
if errorlevel 1 goto err_models

echo.
echo [4/4] Готово! Запускай «Рассказчик» ярлыком на рабочем столе.
pause
exit /b 0

:err_python
echo.
echo Не удалось поставить Python. Проверь интернет и запусти установку ещё раз (ярлык «Рассказчик: доустановить»).
pause
exit /b 1

:err_venv
echo.
echo Не удалось создать окружение. Пришли скриншот этого окна.
pause
exit /b 1

:err_pip
echo.
echo Ошибка установки библиотек. Проверь интернет, запусти установку ещё раз. Если повторится, пришли скриншот.
pause
exit /b 1

:err_gpu
echo.
echo ВНИМАНИЕ: PyTorch не видит видеокарту. Обнови драйвер NVIDIA с nvidia.com и запусти установку ещё раз.
pause
exit /b 1

:err_models
echo.
echo Ошибка при скачивании моделей. Проверь интернет и запусти установку ещё раз: скачанное не пропадёт.
pause
exit /b 1
