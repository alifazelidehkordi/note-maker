@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" call setup.cmd

set "OPML_DIR=%OPML_DIR%"
if "%OPML_DIR%"=="" set "OPML_DIR=outputs\opml"

set "XMIND_DIR=%XMIND_DIR%"
if "%XMIND_DIR%"=="" set "XMIND_DIR=outputs\xmind"

echo === OPML -^> XMind only ===
echo OPML dir : %OPML_DIR%
echo XMind dir: %XMIND_DIR%

".venv\Scripts\python.exe" scripts\convert_opml_batch.py ^
  --opml-dir "%OPML_DIR%" ^
  --xmind-dir "%XMIND_DIR%" ^
  %*

exit /b %ERRORLEVEL%