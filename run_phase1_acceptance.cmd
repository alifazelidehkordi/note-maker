@echo off
setlocal
cd /d "%~dp0"
set "PYTHON=.venv-win\Scripts\python.exe"
if not exist "%PYTHON%" set "PYTHON=python"
"%PYTHON%" scripts\phase1_acceptance.py %*
exit /b %ERRORLEVEL%
