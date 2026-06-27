@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" call setup.cmd

if "%MARKDOWN_FILE%"=="" (
  echo ERROR: Set MARKDOWN_FILE to your source .md file.
  echo Example:
  echo   set MARKDOWN_FILE=C:\path\to\notes.md
  echo   run_md_to_xmind.cmd --overwrite
  exit /b 1
)

set "OPML_DIR=%OPML_DIR%"
if "%OPML_DIR%"=="" set "OPML_DIR=outputs\opml"

set "XMIND_DIR=%XMIND_DIR%"
if "%XMIND_DIR%"=="" set "XMIND_DIR=outputs\xmind"

set "PROMPT_FILE=%PROMPT_FILE%"
if "%PROMPT_FILE%"=="" set "PROMPT_FILE=prompts\prompt-mind-map.md"

echo === Markdown -^> OPML -^> XMind Pipeline (Windows) ===
echo Markdown file: %MARKDOWN_FILE%
echo OPML dir     : %OPML_DIR%
echo XMind dir    : %XMIND_DIR%
echo Prompt       : %PROMPT_FILE%
echo.

".venv\Scripts\python.exe" scripts\pipeline.py markdown ^
  --markdown-file "%MARKDOWN_FILE%" ^
  --opml-dir "%OPML_DIR%" ^
  --xmind-dir "%XMIND_DIR%" ^
  --prompt "%PROMPT_FILE%" ^
  %*

echo.
echo Final XMind files: %XMIND_DIR%\
exit /b %ERRORLEVEL%