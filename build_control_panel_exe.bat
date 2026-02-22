@echo off
chcp 65001 >NUL
setlocal EnableExtensions

set NO_PAUSE=0
if /I "%~1"=="--no-pause" set NO_PAUSE=1

echo ========================================
echo Build control_panel.exe (Windows)
echo ========================================

where py >NUL 2>&1
if errorlevel 1 goto :NO_PY

py -m pip install pyinstaller
if errorlevel 1 goto :PIP_FAIL

py -m PyInstaller --onefile --noconsole --name control_panel control_panel_launcher.py
if errorlevel 1 goto :BUILD_FAIL

copy /Y dist\control_panel.exe . >NUL
if errorlevel 1 goto :COPY_FAIL

echo.
echo DONE: control_panel.exe created.
echo.
if "%NO_PAUSE%"=="0" pause
exit /b 0

:NO_PY
echo ERROR: Python launcher 'py' not found.
if "%NO_PAUSE%"=="0" pause
exit /b 1

:PIP_FAIL
echo ERROR: pyinstaller installation failed.
if "%NO_PAUSE%"=="0" pause
exit /b 1

:BUILD_FAIL
echo ERROR: exe build failed.
if "%NO_PAUSE%"=="0" pause
exit /b 1

:COPY_FAIL
echo ERROR: copy dist\\control_panel.exe failed.
if "%NO_PAUSE%"=="0" pause
exit /b 1
