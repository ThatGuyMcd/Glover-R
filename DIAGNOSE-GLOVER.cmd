@echo off
call "%~dp0ONE-CLICK-BUILD.cmd" -PreflightOnly %*
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" pause
exit /b %RC%
