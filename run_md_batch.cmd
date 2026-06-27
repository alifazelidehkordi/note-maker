@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" call setup.cmd

if "%MARKDOWN_FILE%"=="" (
  echo ERROR: Set MARKDOWN_FILE to your source .md file.
  echo Example:
  echo   set MARKDOWN_FILE=C:\path\to\notes.md
  echo   run_md_batch.cmd --overwrite
  exit /b 1
)

set "OUTPUT_DIR=%OUTPUT_DIR%"
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=outputs\markdown"

set "PROMPT_FILE=%PROMPT_FILE%"
if "%PROMPT_FILE%"=="" set "PROMPT_FILE=prompts\prompt-mind-map.md"

echo === ChatGPT Mind Map - Markdown Sections Batch (Windows) ===
echo Markdown file: %MARKDOWN_FILE%
echo Output dir   : %OUTPUT_DIR%
echo Prompt       : %PROMPT_FILE%
echo.

".venv\Scripts\python.exe" scripts\batch_markdown.py ^
  --markdown-file "%MARKDOWN_FILE%" ^
  --output-dir "%OUTPUT_DIR%" ^
  --prompt "%PROMPT_FILE%" ^
  %*

exit /b %ERRORLEVEL%