@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>nul
if errorlevel 1 (
  echo Necesitas Python 3.10 o superior: https://www.python.org/downloads/  ^(marca "Add python.exe to PATH"^)
  pause & exit /b 1
)
if not exist .venv\Scripts\python.exe (
  echo Preparando entorno ^(solo la primera vez^)...
  python -m venv .venv || (pause & exit /b 1)
  .venv\Scripts\python -m pip install -q -r requirements.txt waitress || (pause & exit /b 1)
)
.venv\Scripts\python run_local.py
pause
