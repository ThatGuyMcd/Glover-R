@echo off
call "%~dp0ONE-CLICK-BUILD.cmd" -CollectDiagnostics %*
exit /b %ERRORLEVEL%
