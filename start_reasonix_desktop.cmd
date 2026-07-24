@echo off
setlocal
title Reasonix Desktop Frontend

set "REASONIX_HOME=%~dp0"
set "PYTHON_EXE=%REASONIX_HOME%reasonix.exe"
set "DESKTOP_URL=http://127.0.0.1:8080/desktop"

if not exist "%PYTHON_EXE%" (
    echo [Reasonix] Missing bundled executable:
    echo   "%PYTHON_EXE%"
    pause
    exit /b 1
)

if "%DEEPSEEK_API_KEY%"=="" (
    echo [Reasonix] DEEPSEEK_API_KEY is not set.
    echo [Reasonix] The desktop UI can open, but chat will need a model key.
    echo [Reasonix] Set it with:
    echo   set DEEPSEEK_API_KEY=your_api_key_here
)

echo [Reasonix] Opening desktop frontend: %DESKTOP_URL%
start "" "%DESKTOP_URL%"
echo [Reasonix] Starting local Reasonix server. Close this window to stop it.
"%PYTHON_EXE%" serve
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo [Reasonix] reasonix.exe serve exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
