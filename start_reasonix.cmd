@echo off
setlocal
title Reasonix - AI Coding Agent

set "REASONIX_HOME=%~dp0"
set "PYTHON_EXE=%REASONIX_HOME%reasonix.exe"

if not exist "%PYTHON_EXE%" (
    echo [Reasonix] Missing bundled executable:
    echo   "%PYTHON_EXE%"
    pause
    exit /b 1
)

if "%DEEPSEEK_API_KEY%"=="" (
    echo [Reasonix] DEEPSEEK_API_KEY is not set, so chat cannot start.
    echo [Reasonix] Set it in this terminal:
    echo   set DEEPSEEK_API_KEY=your_api_key_here
    echo [Reasonix] Or set it permanently in Windows Environment Variables.
    pause
    exit /b 2
)

echo [Reasonix] Starting terminal UI...
"%PYTHON_EXE%" chat
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo [Reasonix] reasonix.exe exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
