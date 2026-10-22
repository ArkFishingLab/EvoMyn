@echo off
setlocal
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0bootstrap.ps1" -Action start
if errorlevel 1 pause
exit /b %errorlevel%
