@echo off
REM Cortex full-stack smoke gate (Windows).
REM Usage: scripts\smoke.bat [--skip-infra]
setlocal
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0smoke.ps1" %*
endlocal & exit /b %ERRORLEVEL%
