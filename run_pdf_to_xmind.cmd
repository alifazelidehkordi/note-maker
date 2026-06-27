@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" call setup.cmd

set "INPUT_DIR=%INPUT_DIR%"
if "%INPUT_DIR%"=="" set "INPUT_DIR=inputs"

set "OPML_DIR=%OPML_DIR%"
if "%OPML_DIR%"=="" set "OPML_DIR=outputs\opml"

set "XMIND_DIR=%XMIND_DIR%"
if "%XMIND_DIR%"=="" set "XMIND_DIR=outputs\xmind"

set "PROMPT_FILE=%PROMPT_FILE%"
if "%PROMPT_FILE%"=="" set "PROMPT_FILE=prompts\prompt-mind-map.md"

echo === PDF/DOCX -^> OPML -^> XMind Pipeline (Windows) ===
echo Input dir : %INPUT_DIR%
echo OPML dir  : %OPML_DIR%
echo XMind dir : %XMIND_DIR%
echo Prompt    : %PROMPT_FILE%
echo.

".venv\Scripts\python.exe" scripts\pipeline.py pdf ^
  --input-dir "%INPUT_DIR%" ^
  --opml-dir "%OPML_DIR%" ^
  --xmind-dir "%XMIND_DIR%" ^
  --prompt "%PROMPT_FILE%" ^
  %*

echo.
echo Final XMind files: %XMIND_DIR%\
exit /b %ERRORLEVEL%