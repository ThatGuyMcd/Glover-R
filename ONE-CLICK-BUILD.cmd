@echo off
setlocal
cd /d "%~dp0"
title Glover-R One Click Builder
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\OneClickBuild.ps1" %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="20" (
    echo.
    echo Complete the prerequisite action described above, then run this file again.
    pause
    exit /b %RC%
)
if not "%RC%"=="0" (
    echo.
    echo Glover-R build stopped with exit code %RC%.
    echo See build\logs and the diagnostic ZIP in dist.
    pause
)
exit /b %RC%
