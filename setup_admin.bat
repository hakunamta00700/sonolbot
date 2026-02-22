@echo off
setlocal EnableExtensions EnableDelayedExpansion
chcp 65001 >NUL 2>&1

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
if not exist "%PROJECT_DIR%\logs" mkdir "%PROJECT_DIR%\logs" >NUL 2>&1

set "MSG_SCRIPT=%PROJECT_DIR%\scripts\setup_messages.ps1"
set "UI_LANG=en"
for /f "delims=" %%I in ('powershell -NoProfile -Command "(Get-Culture).TwoLetterISOLanguageName" 2^>NUL') do set "UI_LANG=%%I"
if /I not "%UI_LANG%"=="ko" set "UI_LANG=en"
if /I "%SONOLBOT_UI_LANG%"=="ko" set "UI_LANG=ko"
if /I "%SONOLBOT_UI_LANG%"=="en" set "UI_LANG=en"

set "RUN_TS="
for /f "delims=" %%I in ('powershell -NoProfile -Command "(Get-Date).ToString(\"yyyyMMdd-HHmmss\")" 2^>NUL') do set "RUN_TS=%%I"
if not defined RUN_TS set "RUN_TS=latest"

set "SETUP_LOG=%PROJECT_DIR%\logs\setup-run-%RUN_TS%.log"
set "SETUP_LOG_LATEST=%PROJECT_DIR%\logs\setup-run.log"

if /I "%~1"=="__run_internal__" goto run_internal

echo ========================================
call :msg setup_title
echo ========================================
call :msg setup_notice_components
call :msg setup_notice_components_2
call :msg setup_req_1
call :msg setup_req_2
call :msg setup_req_3
call :msg setup_req_4
call :msg setup_req_5
call :msg setup_req_6
call :msg setup_req_7
echo.
call :get_msg LOG_LABEL setup_log_file_label
echo %LOG_LABEL%: %SETUP_LOG%
call :msg setup_may_pause
echo.

set "SONOLBOT_SETUP_NONINTERACTIVE=1"
call "%~f0" __run_internal__ > "%SETUP_LOG%" 2>&1
set "EC=%ERRORLEVEL%"
copy /Y "%SETUP_LOG%" "%SETUP_LOG_LATEST%" >NUL 2>&1

echo.
call :get_msg LOG_LABEL setup_log_label
echo %LOG_LABEL%: %SETUP_LOG%
if not "%EC%"=="0" (
    call :get_msg FAIL_LABEL setup_fail
    echo %FAIL_LABEL% (exit code: %EC%)
) else (
    call :msg setup_ok
    echo.
    call :get_msg RUN_PANEL_PROMPT prompt_run_panel
    if exist "%SETUP_LOG%" echo [%DATE% %TIME%] panel_prompt_shown timeout=20 default=N>>"%SETUP_LOG%"
    call :clear_console_input_buffer
    choice /C YN /N /T 20 /D N /M "%RUN_PANEL_PROMPT%"
    set "CHOICE_EC=!ERRORLEVEL!"
    set "RUN_PANEL=N"
    if "!CHOICE_EC!"=="1" set "RUN_PANEL=Y"
    if "!CHOICE_EC!"=="2" set "RUN_PANEL=N"
    if exist "%SETUP_LOG%" echo [%DATE% %TIME%] panel_prompt_answer=!RUN_PANEL! ec=!CHOICE_EC!>>"%SETUP_LOG%"
    if /I "!RUN_PANEL!"=="Y" (
        call :launch_control_panel
    ) else (
        if exist "%SETUP_LOG%" echo [%DATE% %TIME%] panel_launch skipped by user>>"%SETUP_LOG%"
    )
)

echo.
call :msg press_any_key
pause >NUL
exit /b %EC%

:run_internal
shift /1

echo ========================================
call :msg wsl_setup_launcher
echo ========================================
echo.

set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
set "WSL_SCRIPT=setup_wsl.sh"

where wsl.exe >NUL 2>&1
if errorlevel 1 (
    call :msg wsl_not_installed
    call :msg wsl_install_hint
    exit /b 1
)

call :apply_wsl_dns_hardening
echo.

for /f "delims=" %%I in ('wsl.exe wslpath -a "%PROJECT_DIR%" 2^>NUL') do set "WSL_PROJECT=%%I"
if not defined WSL_PROJECT (
    call :msg wsl_path_convert_fail
    exit /b 1
)

set "WSL_SETUP_SCRIPT=%WSL_PROJECT%/%WSL_SCRIPT%"
if defined WSL_DISTRO (
    wsl.exe -d "%WSL_DISTRO%" -e test -f "%WSL_SETUP_SCRIPT%" >NUL 2>&1
) else (
    wsl.exe -e test -f "%WSL_SETUP_SCRIPT%" >NUL 2>&1
)
if not "%ERRORLEVEL%"=="0" (
    call :get_msg WSL_SCRIPT_MISSING wsl_script_missing
    echo %WSL_SCRIPT_MISSING%: %WSL_SETUP_SCRIPT%
    exit /b 1
)

call :get_msg PROJECT_PATH_LABEL project_path_label
echo %PROJECT_PATH_LABEL%: %PROJECT_DIR%
call :get_msg WSL_PATH_LABEL wsl_path_label
echo %WSL_PATH_LABEL%: %WSL_PROJECT%
echo.
call :msg run_setup_wsl
echo.

if defined WSL_DISTRO (
    wsl.exe -d "%WSL_DISTRO%" -e env SONOLBOT_UI_LANG=%UI_LANG% /bin/bash "%WSL_SETUP_SCRIPT%"
) else (
    wsl.exe -e env SONOLBOT_UI_LANG=%UI_LANG% /bin/bash "%WSL_SETUP_SCRIPT%"
)

set "EC=%ERRORLEVEL%"
echo.
if "%EC%"=="0" (
    call :msg setup_wsl_ok
) else (
    call :get_msg SETUP_WSL_FAIL setup_wsl_fail
    echo %SETUP_WSL_FAIL% (exit code: %EC%)
)
echo.
exit /b %EC%

:launch_control_panel
if not exist "%PROJECT_DIR%\control_panel.exe" (
    call :msg cp_missing_1
    call :msg cp_missing_2
    if exist "%SETUP_LOG%" echo [%DATE% %TIME%] panel_launch blocked: exe missing>>"%SETUP_LOG%"
    exit /b 0
)

set "WIN_TK_OK=0"
if exist "%PROJECT_DIR%\.venv\Scripts\python.exe" (
    "%PROJECT_DIR%\.venv\Scripts\python.exe" -c "import tkinter" >NUL 2>&1
    if not errorlevel 1 set "WIN_TK_OK=1"
)
if "!WIN_TK_OK!"=="0" (
    where py.exe >NUL 2>&1
    if not errorlevel 1 (
        py -3 -c "import tkinter" >NUL 2>&1
        if not errorlevel 1 set "WIN_TK_OK=1"
    )
)
if "!WIN_TK_OK!"=="0" (
    where python.exe >NUL 2>&1
    if not errorlevel 1 (
        python -c "import tkinter" >NUL 2>&1
        if not errorlevel 1 set "WIN_TK_OK=1"
    )
)
if "!WIN_TK_OK!"=="0" (
    call :msg tk_missing_1
    call :msg tk_missing_2
    if exist "%SETUP_LOG%" echo [%DATE% %TIME%] panel_launch blocked: windows tkinter missing>>"%SETUP_LOG%"
    exit /b 0
)

where powershell.exe >NUL 2>&1
if errorlevel 1 (
    start "" /D "%PROJECT_DIR%" "%PROJECT_DIR%\control_panel.exe"
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -FilePath '%PROJECT_DIR%\control_panel.exe' -WorkingDirectory '%PROJECT_DIR%'"
    if errorlevel 1 (
        if exist "%SETUP_LOG%" echo [%DATE% %TIME%] panel_launch failed via powershell, fallback start>>"%SETUP_LOG%"
        start "" /D "%PROJECT_DIR%" "%PROJECT_DIR%\control_panel.exe"
    )
)
if exist "%SETUP_LOG%" echo [%DATE% %TIME%] panel_launch requested>>"%SETUP_LOG%"
exit /b 0

:apply_wsl_dns_hardening
setlocal EnableExtensions
set "WSL_DNS_SCRIPT=%PROJECT_DIR%\scripts\configure_wsl_dns.ps1"
set "WSL_DNS_CHANGED=0"
set "WSL_DNS_MODE_ARG="

call :msg wsl_dns_check
call :is_elevated_admin
if errorlevel 1 (
    call :msg wsl_dns_skip_nonadmin_1
    call :msg wsl_dns_skip_nonadmin_2
    endlocal & exit /b 0
)

if not exist "%WSL_DNS_SCRIPT%" (
    call :get_msg DNS_SCRIPT_MISSING wsl_dns_script_missing
    echo %DNS_SCRIPT_MISSING%: %WSL_DNS_SCRIPT%
    endlocal & exit /b 0
)

where powershell.exe >NUL 2>&1
if errorlevel 1 (
    call :msg wsl_dns_ps_missing
    endlocal & exit /b 0
)

if /I "%SONOLBOT_WSL_NETWORKING_MODE%"=="nat" set "WSL_DNS_MODE_ARG=-NetworkingMode nat"
if /I "%SONOLBOT_WSL_NETWORKING_MODE%"=="mirrored" set "WSL_DNS_MODE_ARG=-NetworkingMode mirrored"
if /I "%SONOLBOT_WSL_NETWORKING_MODE%"=="virtioproxy" set "WSL_DNS_MODE_ARG=-NetworkingMode virtioproxy"

set "WSL_DNS_OUT=%TEMP%\sonolbot-wsl-dns-%RANDOM%-%RANDOM%.log"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%WSL_DNS_SCRIPT%" %WSL_DNS_MODE_ARG% > "%WSL_DNS_OUT%" 2>&1
set "WSL_DNS_PS_EC=%ERRORLEVEL%"
type "%WSL_DNS_OUT%"
findstr /B /C:"CHANGED=1" "%WSL_DNS_OUT%" >NUL 2>&1
if not errorlevel 1 set "WSL_DNS_CHANGED=1"
del /Q "%WSL_DNS_OUT%" >NUL 2>&1

if not "%WSL_DNS_PS_EC%"=="0" (
    call :msg wsl_dns_apply_fail
    endlocal & exit /b 0
)

if "%WSL_DNS_CHANGED%"=="1" (
    call :msg wsl_dns_updated
    wsl.exe --shutdown >NUL 2>&1
    if errorlevel 1 (
        call :msg wsl_shutdown_warn
    ) else (
        call :msg wsl_shutdown_ok
    )
) else (
    call :msg wsl_dns_already_ok
)

endlocal & exit /b 0

:is_elevated_admin
setlocal EnableExtensions
where powershell.exe >NUL 2>&1
if errorlevel 1 (
    fltmc >NUL 2>&1
    if errorlevel 1 (
        endlocal & exit /b 1
    ) else (
        endlocal & exit /b 0
    )
)

powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$p=[Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent(); if($p.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)){exit 0}else{exit 1}" >NUL 2>&1
set "ADMIN_EC=%ERRORLEVEL%"
if "%ADMIN_EC%"=="0" (
    endlocal & exit /b 0
)

fltmc >NUL 2>&1
if errorlevel 1 (
    endlocal & exit /b 1
) else (
    endlocal & exit /b 0
)

:clear_console_input_buffer
setlocal EnableExtensions
where powershell.exe >NUL 2>&1
if errorlevel 1 (
    endlocal & exit /b 0
)
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='SilentlyContinue'; try { $Host.UI.RawUI.FlushInputBuffer() } catch {}" >NUL 2>&1
endlocal & exit /b 0

:msg
setlocal EnableExtensions
set "MSG_KEY=%~1"
set "MSG_TEXT="
if exist "%MSG_SCRIPT%" (
    for /f "delims=" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%MSG_SCRIPT%" -Key "%MSG_KEY%" -Lang "%UI_LANG%" 2^>NUL') do set "MSG_TEXT=%%I"
)
if not defined MSG_TEXT set "MSG_TEXT=%MSG_KEY%"
echo %MSG_TEXT%
endlocal & exit /b 0

:get_msg
setlocal EnableExtensions
set "OUT_VAR=%~1"
set "MSG_KEY=%~2"
set "MSG_TEXT="
if exist "%MSG_SCRIPT%" (
    for /f "delims=" %%I in ('powershell -NoProfile -ExecutionPolicy Bypass -File "%MSG_SCRIPT%" -Key "%MSG_KEY%" -Lang "%UI_LANG%" 2^>NUL') do set "MSG_TEXT=%%I"
)
if not defined MSG_TEXT set "MSG_TEXT=%MSG_KEY%"
endlocal & set "%~1=%MSG_TEXT%" & exit /b 0
