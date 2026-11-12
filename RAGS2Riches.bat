@echo off
rem Run RAGS2Riches from source. Creates .venv and installs requirements on first run.
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3.12 -m venv .venv || py -3 -m venv .venv || goto :fail
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn, langgraph, langchain, sqlalchemy, pandas, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies ^(first run only, may take several minutes^)...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

".venv\Scripts\python.exe" launcher.py
exit /b %errorlevel%

:fail
echo.
echo Setup failed. See the messages above.
pause
exit /b 1
