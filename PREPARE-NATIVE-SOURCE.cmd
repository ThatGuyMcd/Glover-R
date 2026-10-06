@echo off
call "%~dp0ONE-CLICK-BUILD.cmd" -PrepareOnly %*
exit /b %ERRORLEVEL%
