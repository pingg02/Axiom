@echo off
setlocal
title Reasonix - AI Coding Agent (Full)

set "REASONIX_HOME=%~dp0"
set "PYTHON_EXE=%REASONIX_HOME%reasonix.exe"
set "JAVA_JAR=%REASONIX_HOME%reasonix-java\target\reasonix-security.jar"
set "JAVA_PID="

if not exist "%PYTHON_EXE%" (
    echo [Reasonix] Missing bundled executable:
    echo   "%PYTHON_EXE%"
    pause
    exit /b 1
)

if exist "%JAVA_JAR%" (
    where java >nul 2>nul
    if "%ERRORLEVEL%"=="0" (
        echo [Reasonix] Starting Java security service...
        for /f %%p in ('powershell -NoProfile -ExecutionPolicy Bypass -Command "$out = Join-Path $env:TEMP 'reasonix-java.log'; $err = Join-Path $env:TEMP 'reasonix-java.err'; $p = Start-Process -FilePath 'java' -ArgumentList @('-jar', '%JAVA_JAR%') -RedirectStandardOutput $out -RedirectStandardError $err -PassThru; $p.Id"') do set "JAVA_PID=%%p"
        if not "%JAVA_PID%"=="" (
            echo [Reasonix] Java security service started. PID: %JAVA_PID%
            timeout /t 3 /nobreak >nul
        )
    ) else (
        echo [Reasonix] Java is not installed; continuing with Python-only mode.
    )
) else (
    echo [Reasonix] Java security jar not found; continuing with Python-only mode.
)

if "%DEEPSEEK_API_KEY%"=="" (
    echo [Reasonix] DEEPSEEK_API_KEY is not set, so chat cannot start.
    echo [Reasonix] Set it in this terminal:
    echo   set DEEPSEEK_API_KEY=your_api_key_here
    echo [Reasonix] Or set it permanently in Windows Environment Variables.
    if not "%JAVA_PID%"=="" (
        echo [Reasonix] Stopping Java security service...
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Stop-Process -Id %JAVA_PID% -Force -ErrorAction SilentlyContinue" >nul 2>nul
    )
    pause
    exit /b 2
)

echo [Reasonix] Starting terminal UI...
"%PYTHON_EXE%" chat
set "EXIT_CODE=%ERRORLEVEL%"

if not "%JAVA_PID%"=="" (
    echo [Reasonix] Stopping Java security service...
    powershell -NoProfile -ExecutionPolicy Bypass -Command "Stop-Process -Id %JAVA_PID% -Force -ErrorAction SilentlyContinue" >nul 2>nul
)

if not "%EXIT_CODE%"=="0" (
    echo [Reasonix] reasonix.exe exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
