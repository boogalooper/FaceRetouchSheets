@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "RET_DEVICE=%~1"
if /i "%RET_DEVICE%"=="cpu" goto :install
if /i "%RET_DEVICE%"=="gpu" goto :install
if not "%RET_DEVICE%"=="" (
    echo Usage: install.bat [cpu^|gpu]
    exit /b 2
)
choice /c CG /n /m "Install for [C] CPU or [G] NVIDIA GPU? "
if not errorlevel 1 exit /b 2
if errorlevel 3 exit /b 2
if errorlevel 2 (
    set "RET_DEVICE=gpu"
) else (
    set "RET_DEVICE=cpu"
)
:install
echo Python package connection mode:
echo   [1] Normal secure mode
echo   [2] Kaspersky compatibility for official PyPI hosts
echo   [3] Cancel
choice /c 123 /n /m "Choose 1, 2 or 3: "
if not errorlevel 1 exit /b 2
if errorlevel 3 exit /b 2
set "RET_TLS="
if errorlevel 2 set "RET_TLS=-KasperskyCompatibility"
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup\install.ps1" -Device "%RET_DEVICE%" %RET_TLS%
set "RET_CODE=%ERRORLEVEL%"
if not "%RET_CODE%"=="0" echo See "%~dp0install.log"
if "%~1"=="" pause
exit /b %RET_CODE%
