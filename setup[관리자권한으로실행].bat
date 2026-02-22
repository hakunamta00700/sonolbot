@echo off
setlocal EnableExtensions
set "PROJECT_DIR=%~dp0"
if "%PROJECT_DIR:~-1%"=="\" set "PROJECT_DIR=%PROJECT_DIR:~0,-1%"
call "%PROJECT_DIR%\setup_admin.bat" %*
exit /b %ERRORLEVEL%
