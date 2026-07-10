@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" call setup.cmd
if errorlevel 1 exit /b %ERRORLEVEL%

".venv\Scripts\python.exe" scripts\profile_bootstrap.py login %*
exit /b %ERRORLEVEL%
