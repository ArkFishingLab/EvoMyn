@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\workspace.ps1" -Action Configure %*
set "result=%errorlevel%"
if not "%result%"=="0" pause
exit /b %result%
