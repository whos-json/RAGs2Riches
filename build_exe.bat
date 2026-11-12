@echo off
rem Build dist\RAGS2Riches.exe (single file) with PyInstaller.
rem Requires the project dependencies in .venv (run RAGS2Riches.bat once first).
setlocal
cd /d "%~dp0"

set "PY=.venv\Scripts\python.exe"
if not exist "%PY%" (
  echo .venv not found. Run RAGS2Riches.bat once to set it up, then re-run this script.
  exit /b 1
)

"%PY%" -m pip install --upgrade pyinstaller || goto :fail

rem Bundle the UAT workbook so the exe can seed its database on first launch.
if exist "build\seed" rmdir /s /q "build\seed"
mkdir "build\seed"
if defined SOURCE_XLSX (
  copy /y "%SOURCE_XLSX%" "build\seed\mock leasing data.xlsx" >nul
) else (
  copy /y "%USERPROFILE%\Downloads\mock leasing data.xlsx" "build\seed\mock leasing data.xlsx" >nul
)
if errorlevel 1 echo WARNING: workbook not found; the exe will start with an empty database.

"%PY%" -m PyInstaller --noconfirm --clean --onefile --console --name RAGS2Riches ^
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
  --hidden-import pandas ^
  --hidden-import openpyxl ^
  launcher.py || goto :fail

echo.
echo Built: %~dp0dist\RAGS2Riches.exe
echo Double-click it to start the server and open the browser.
exit /b 0

:fail
echo.
echo Build failed. See the messages above.
exit /b 1
