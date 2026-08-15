@echo off
setlocal
if "%~1"=="" (
  echo Usage: scan_custom_nodes.cmd ^<ComfyUI root or portable root^> [output directory]
  exit /b 2
)
set "SCRIPT_DIR=%~dp0"
set "OUTPUT_DIR=%~2"
if "%OUTPUT_DIR%"=="" set "OUTPUT_DIR=%SCRIPT_DIR%..\docs"
python "%SCRIPT_DIR%scan_custom_nodes.py" --comfy-root "%~1" --output-dir "%OUTPUT_DIR%"
endlocal
