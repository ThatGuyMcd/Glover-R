@echo off
setlocal
cd /d "%~dp0"
set "GLOVER_EXE=%~dp0build\native-src\build\windows\bin\Release\Glover-R.exe"
set "GLOVER_ROM=%~dp0build\private\glover.us.z64"
if not exist "%GLOVER_EXE%" (
    echo Build Glover-R with ONE-CLICK-BUILD.cmd first.
    pause
    exit /b 1
)
if exist "%GLOVER_ROM%" (
    "%GLOVER_EXE%" --rom "%GLOVER_ROM%" --launch
) else (
    "%GLOVER_EXE%"
)
set "GLOVER_RC=%ERRORLEVEL%"
if not "%GLOVER_RC%"=="0" (
    echo Glover-R exited with code %GLOVER_RC%. Logs are in %%APPDATA%%\Glover-R.
    pause
)
exit /b %GLOVER_RC%
