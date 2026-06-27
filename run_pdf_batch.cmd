@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" call setup.cmd

set "INPUT_DIR=%INPUT_DIR%"
if "%INPUT_DIR%"=="" set "INPUT_DIR=inputs"

set "OUTPUT_DIR=%OUTPUT_DIR%"
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=outputs"

set "PROMPT_FILE=%PROMPT_FILE%"
if "%PROMPT_FILE%"=="" set "PROMPT_FILE=prompts\prompt-mind-map.md"

echo === ChatGPT Mind Map - PDF/DOCX Batch (Windows) ===
echo Input dir : %INPUT_DIR%
echo Output dir: %OUTPUT_DIR%
echo Prompt    : %PROMPT_FILE%
echo.

".venv\Scripts\python.exe" scripts\batch_pdf.py ^
  --input-dir "%INPUT_DIR%" ^
  --output-dir "%OUTPUT_DIR%" ^
  --prompt "%PROMPT_FILE%" ^
  %*

exit /b %ERRORLEVEL%