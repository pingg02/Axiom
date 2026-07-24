@echo off
setlocal

set "MAVEN_VERSION=3.9.16"
set "MAVEN_CACHE=%~dp0.mvn"
set "MAVEN_ROOT=%MAVEN_CACHE%\apache-maven-%MAVEN_VERSION%"
set "MAVEN_BIN=%MAVEN_ROOT%\bin\mvn.cmd"
set "MAVEN_ZIP=%MAVEN_CACHE%\apache-maven-%MAVEN_VERSION%-bin.zip"
set "MAVEN_URL=https://dlcdn.apache.org/maven/maven-3/%MAVEN_VERSION%/binaries/apache-maven-%MAVEN_VERSION%-bin.zip"

if not exist "%MAVEN_BIN%" (
    echo [mvnw] Downloading Apache Maven %MAVEN_VERSION%...
    if not exist "%MAVEN_CACHE%" mkdir "%MAVEN_CACHE%"
    powershell -NoProfile -NonInteractive -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri '%MAVEN_URL%' -OutFile '%MAVEN_ZIP%'; Expand-Archive -LiteralPath '%MAVEN_ZIP%' -DestinationPath '%MAVEN_CACHE%' -Force; Remove-Item -LiteralPath '%MAVEN_ZIP%' -Force"
    if errorlevel 1 (
        echo [mvnw] Maven download or extraction failed.
        exit /b 1
    )
)

if not exist "%MAVEN_BIN%" (
    echo [mvnw] Maven executable was not found after extraction.
    exit /b 1
)

call "%MAVEN_BIN%" -Dmaven.repo.local="%MAVEN_CACHE%\repository" %*
exit /b %errorlevel%
