@echo off
rem RAGS2Riches: the single launcher.
rem
rem   RAGS2Riches.bat          Set up (first run only) and open the app window.
rem   RAGS2Riches.bat build    Also produce dist\RAGS2Riches.exe, which runs the same
rem                            launcher.py with no Python install needed.
rem
rem Runtime logs go to data\launcher.log.
setlocal
cd /d "%~dp0"

call :ensure_env || goto :fail
if /i "%~1"=="build" goto :build

start "" ".venv\Scripts\pythonw.exe" launcher.py
exit /b 0

:ensure_env
if not exist ".venv\Scripts\python.exe" (
  echo Creating virtual environment...
  py -3.12 -m venv .venv || py -3 -m venv .venv || exit /b 1
)
".venv\Scripts\python.exe" -c "import fastapi, uvicorn, langgraph, langchain, sqlalchemy, pandas, openpyxl, webview" >nul 2>&1
if errorlevel 1 (
  echo Installing dependencies ^(first run only, may take several minutes^)...
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt || exit /b 1
)
exit /b 0

:build
".venv\Scripts\python.exe" -m pip install --upgrade pyinstaller || goto :fail

rem Bundle the UAT workbook so the exe can seed its database on first launch.
if exist "build\seed" rmdir /s /q "build\seed"
mkdir "build\seed"
if defined SOURCE_XLSX (
  copy /y "%SOURCE_XLSX%" "build\seed\mock leasing data.xlsx" >nul
) else (
  copy /y "%USERPROFILE%\Downloads\mock leasing data.xlsx" "build\seed\mock leasing data.xlsx" >nul
)
if errorlevel 1 echo WARNING: workbook not found; the exe will start with an empty database.

".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --onefile --noconsole --name RAGS2Riches ^
  --add-data "app\static;app\static" ^
  --add-data "build\seed;seed" ^
  --collect-submodules langchain ^
  --collect-submodules langchain_core ^
  --collect-submodules langgraph ^
  --collect-submodules langchain_ollama ^
  --collect-submodules langchain_openai ^
  --collect-submodules langchain_anthropic ^
  --collect-submodules uvicorn ^
  --collect-submodules sqlalchemy.dialects.sqlite ^
  --collect-submodules webview ^
  --hidden-import pandas ^
  --hidden-import openpyxl ^
  launcher.py || goto :fail

echo.
echo Built: %~dp0dist\RAGS2Riches.exe
exit /b 0

:fail
echo.
echo Failed. See the messages above.
pause
exit /b 1
