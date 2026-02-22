@echo off
chcp 65001 >NUL
if /I "%~1"=="__run_internal__" goto run_internal

setlocal EnableExtensions
set "SILENT_MODE=0"
if /I "%~1"=="__silent__" (
    set "SILENT_MODE=1"
    shift /1
)
set "FORWARD_ARGS=%*"
set "SONOLBOT_UI_LANG=ko"
for /f "delims=" %%I in ('powershell -NoProfile -Command "(Get-Culture).TwoLetterISOLanguageName" 2^>NUL') do set "WIN_LANG=%%I"
if /I not "%WIN_LANG%"=="ko" set "SONOLBOT_UI_LANG=en"

if /I "%SONOLBOT_UI_LANG%"=="ko" (
    set "MSG_PANEL_LOG=control_panel 로그"
    set "MSG_PANEL_FAIL=[오류] control_panel 실행 실패"
    set "MSG_CLOSE_HINT=창을 닫으려면 아무 키나 누르세요."
    set "MSG_PANEL_OK=[정상] control_panel 실행 완료"
    set "MSG_PANEL_SCRIPT_MISSING=[오류] 실행 스크립트를 찾을 수 없습니다:"
    set "MSG_NO_PYTHON=[오류] Windows Python 실행 파일을 찾을 수 없습니다."
    set "MSG_START_PANEL=컨트롤 패널 시작 중..."
    set "MSG_WIN_PATH=  - Windows 경로:"
    set "MSG_PY_PATH=  - Python 경로:"
    set "MSG_PANEL_RUN_FAIL=[오류] 컨트롤 패널 실행 실패"
    set "MSG_TK_HINT_1=tkinter 모듈이 없거나 Python GUI 구성요소가 빠진 상태일 수 있습니다."
    set "MSG_TK_HINT_2=Python 재설치 시 tcl/tk 옵션을 포함해 설치하세요."
) else (
    set "MSG_PANEL_LOG=control_panel log"
    set "MSG_PANEL_FAIL=[Error] control_panel failed"
    set "MSG_CLOSE_HINT=Press any key to close this window."
    set "MSG_PANEL_OK=[OK] control_panel completed"
    set "MSG_PANEL_SCRIPT_MISSING=[Error] Runner script not found:"
    set "MSG_NO_PYTHON=[Error] Windows Python executable was not found."
    set "MSG_START_PANEL=Starting control panel..."
    set "MSG_WIN_PATH=  - Windows path:"
    set "MSG_PY_PATH=  - Python path:"
    set "MSG_PANEL_RUN_FAIL=[Error] control panel failed"
    set "MSG_TK_HINT_1=tkinter may be missing or Python GUI components are not installed."
    set "MSG_TK_HINT_2=Reinstall Python with tcl/tk support enabled."
)

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs" >NUL 2>&1

set "RUN_TS="
for /f "delims=" %%I in ('powershell -NoProfile -Command "(Get-Date).ToString(\"yyyyMMdd-HHmmss\")" 2^>NUL') do set "RUN_TS=%%I"
if not defined RUN_TS set "RUN_TS=latest"
set "PANEL_LOG=%PROJECT_DIR%\logs\control-panel-run-%RUN_TS%.log"
set "PANEL_LOG_LATEST=%PROJECT_DIR%\logs\control-panel-run.log"

call "%~f0" __run_internal__ %FORWARD_ARGS% > "%PANEL_LOG%" 2>&1
set "EC=%ERRORLEVEL%"
copy /Y "%PANEL_LOG%" "%PANEL_LOG_LATEST%" >NUL 2>&1

if "%SILENT_MODE%"=="1" exit /b %EC%

echo.
echo %MSG_PANEL_LOG%: %PANEL_LOG%
if not "%EC%"=="0" (
    echo %MSG_PANEL_FAIL% ^(exit code: %EC%^)
    echo %MSG_CLOSE_HINT%
    pause
) else (
    echo %MSG_PANEL_OK%
)
exit /b %EC%

:run_internal
shift /1
setlocal EnableExtensions

set "PROJECT_DIR=%~dp0"
set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "PANEL_SCRIPT=%PROJECT_DIR%\daemon_control_panel.py"
if not exist "%PANEL_SCRIPT%" (
    echo %MSG_PANEL_SCRIPT_MISSING% %PANEL_SCRIPT%
    exit /b 1
)

set "PYTHON_EXE="
set "PYTHON_ARGS="
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" set "PYTHON_EXE=%PROJECT_DIR%\.venv\Scripts\python.exe"
if not defined PYTHON_EXE (
    where py.exe >NUL 2>&1
    if not errorlevel 1 (
        set "PYTHON_EXE=py"
        set "PYTHON_ARGS=-3"
    )
)
if not defined PYTHON_EXE (
    where python.exe >NUL 2>&1
    if not errorlevel 1 set "PYTHON_EXE=python"
)
if not defined PYTHON_EXE (
    echo %MSG_NO_PYTHON%
    exit /b 1
)

echo %MSG_START_PANEL%
echo %MSG_WIN_PATH% %PROJECT_DIR%
echo %MSG_PY_PATH% %PYTHON_EXE% %PYTHON_ARGS%
echo.

call "%PYTHON_EXE%" %PYTHON_ARGS% "%PANEL_SCRIPT%" %*
set "EC=%ERRORLEVEL%"
if not "%EC%"=="0" (
    echo.
    echo %MSG_PANEL_RUN_FAIL% ^(exit code: %EC%^)
    echo %MSG_TK_HINT_1%
    echo %MSG_TK_HINT_2%
)
exit /b %EC%
