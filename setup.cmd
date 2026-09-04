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
".venv\Scripts\python.exe" -m pip install --no-deps -e .
if not "%SKIP_PATCHRIGHT_BROWSER_INSTALL%"=="1" (
  where chrome.exe >nul 2>nul
  if errorlevel 1 (
    where msedge.exe >nul 2>nul
  )
  if errorlevel 1 (
    ".venv\Scripts\python.exe" -m patchright install chromium
    if errorlevel 1 exit /b 1
  ) else (
    echo System Chrome/Edge detected; skipping Patchright browser download.
  )
)

echo Setup complete.
echo   Interactive CLI: .venv\Scripts\note-maker.exe interactive
echo   PDF -^> XMind : run_pdf_to_xmind.cmd
echo   MD  -^> XMind : run_md_to_xmind.cmd
echo   Login snapshot: run_login.cmd --profile chrome_profile_login --snapshot-name default
