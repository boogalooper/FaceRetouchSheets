@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "RET_DEVICE="
if exist "%~dp0setup\runtime-device.txt" set /p RET_DEVICE=<"%~dp0setup\runtime-device.txt"
if not defined RET_DEVICE if exist "%~dp0runtime-device.txt" set /p RET_DEVICE=<"%~dp0runtime-device.txt"
if /i "%RET_DEVICE%"=="cpu" goto :launch
if /i "%RET_DEVICE%"=="gpu" goto :launch
echo Run install.bat first.
pause
exit /b 1

:launch
set "RET_PYTHON=%~dp0venv-%RET_DEVICE%\Scripts\python.exe"
if not exist "%RET_PYTHON%" (
    echo Run install.bat first.
    pause
    exit /b 1
)
:check_args
if "%~1"=="" goto :gui
if "%~1"=="--cli" goto :cli
if "%~1"=="--help" goto :cli
if "%~1"=="-h" goto :cli
shift
goto :check_args

:gui
set "RET_PYTHONW=%~dp0venv-%RET_DEVICE%\Scripts\pythonw.exe"
if not exist "%RET_PYTHONW%" (
    echo pythonw.exe is missing. Run install.bat to repair the environment.
    pause
    exit /b 1
)
start "" "%RET_PYTHONW%" "%~dp0app\export_faces.py" %*
exit /b %ERRORLEVEL%

:cli
"%RET_PYTHON%" "%~dp0app\export_faces.py" %*
set "RET_CODE=%ERRORLEVEL%"
exit /b %RET_CODE%
