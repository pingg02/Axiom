@echo off
REM Reasonix CLI Launcher
REM 用法: reasonix chat / reasonix run "prompt" / reasonix serve
REM
REM 如果同级目录下有 reasonix-java.jar，自动启动 Java 安全层服务

setlocal enabledelayedexpansion

set JAVA_JAR=%~dp0reasonix-java.jar
set PYTHON_SCRIPT=%~dp0reasonix

:: 启动 Java 安全层（如果有）
if exist "%JAVA_JAR%" (
    echo [reasonix] Starting Java security service...
    start /B "" java -jar "%JAVA_JAR%" > java-service.log 2>&1
    :: 等待 Java 服务就绪
    timeout /t 3 /nobreak >nul
)

:: 启动 Python CLI
if exist "%PYTHON_SCRIPT%.exe" (
    "%PYTHON_SCRIPT%.exe" %*
) else (
    python -m reasonix %*
)

:: 清理 Java 进程
if exist "%JAVA_JAR%" (
    taskkill /F /IM java.exe >nul 2>&1
)

endlocal
