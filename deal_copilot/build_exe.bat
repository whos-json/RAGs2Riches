@echo off
setlocal
cd /d "%~dp0"

set "PY=python"
if exist "..\.venv\Scripts\python.exe" set "PY=..\.venv\Scripts\python.exe"

echo Using %PY%
"%PY%" -m PyInstaller --version >nul 2>&1 || "%PY%" -m pip install pyinstaller || goto :fail

"%PY%" -m unittest test_engine || goto :fail

"%PY%" -m PyInstaller --noconfirm --onefile --console --name DealCopilot ^
  --add-data "web;web" --add-data "data;data" server.py || goto :fail

echo.
echo Built: %~dp0dist\DealCopilot.exe
exit /b 0

:fail
echo.
echo Build failed.
exit /b 1
