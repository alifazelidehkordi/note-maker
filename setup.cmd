@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  py -3 -m venv .venv
  if errorlevel 1 (
    echo Failed to create virtual environment. Install Python 3 and try again.
    exit /b 1
  )
)

".venv\Scripts\python.exe" -m pip install --upgrade pip
".venv\Scripts\python.exe" -m pip install -r requirements.txt

echo Setup complete.
echo   PDF -^> XMind : run_pdf_to_xmind.cmd
echo   MD  -^> XMind : run_md_to_xmind.cmd