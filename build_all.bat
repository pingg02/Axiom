@echo off
setlocal enabledelayedexpansion
REM ===== Reasonix Build Script =====
REM Build: Python exe + Java fatjar + launcher + installer
REM Requires: Python 3.12+, JDK 21+ (optional), Node.js 18+ (optional)
REM Usage:   build_all.bat
REM Output:  reasonix-build\  (next to this script)

set BUILD_DIR=%~dp0reasonix-build
set SRC=%~dp0

echo ========================================
echo Reasonix Build Script
echo Output: %BUILD_DIR%
echo ========================================

REM Clean output dir
if exist "%BUILD_DIR%" rmdir /s /q "%BUILD_DIR%"
mkdir "%BUILD_DIR%"

REM Check tools
where python >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [ERROR] Python not found. Install Python 3.12+.
    pause & exit /b 1
)

REM Step 1/5: Build Python exe
echo [1/5] Building Python exe...
cd /d "%SRC%reasonix-py"
python -m pip install pyinstaller --user >nul 2>&1
python -m PyInstaller reasonix_min.spec
if %ERRORLEVEL% neq 0 (
    echo [ERROR] PyInstaller build failed
    pause & exit /b 1
)
copy /Y "dist\reasonix.exe" "%BUILD_DIR%\"
echo [1/5] Python exe done

REM Step 2/5: Build Java fatjar
echo [2/5] Building Java fatjar...
where mvn >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [SKIP] Maven not found, Java build skipped
) else (
    cd /d "%SRC%reasonix-java"
    call mvn package -DskipTests
    if %ERRORLEVEL% neq 0 (
        echo [ERROR] Maven build failed
        pause & exit /b 1
    )
    mkdir "%BUILD_DIR%\reasonix-java\target" 2>nul
    copy /Y "target\reasonix-security.jar" "%BUILD_DIR%\reasonix-java\target\"
    echo [2/5] Java fatjar done
)

REM Step 3/5: Build frontend
echo [3/5] Building frontend...
where node >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [SKIP] Node.js not found, frontend skipped
) else (
    cd /d "%SRC%desktop\python-frontend"
    if exist "node_modules" (
        call npm install --production
    ) else (
        call npm install
    )
    call npm run build
    if %ERRORLEVEL% equ 0 (
        if exist "dist" (
            xcopy /E /I /Y "dist" "%BUILD_DIR%\frontend\" >nul
            echo [3/5] Frontend build done
        )
    ) else (
        echo [WARN] Frontend build failed
    )
)

REM Step 4/5: Copy launcher scripts
echo [4/5] Copying launchers...
copy "%SRC%start_reasonix_full.cmd" "%BUILD_DIR%\" >nul 2>&1
copy "%SRC%start_reasonix.cmd" "%BUILD_DIR%\" >nul 2>&1
echo [4/5] Launchers copied

REM Step 5/5: Build NSIS installer (optional)
echo [5/5] Building installer...
where makensis >nul 2>nul
if %ERRORLEVEL% neq 0 (
    echo [SKIP] NSIS not found, installer skipped
) else (
    cd /d "%SRC%desktop"
    makensis installer.nsi
    if %ERRORLEVEL% equ 0 (
        copy /Y "Reasonix-windows-amd64-installer.exe" "%BUILD_DIR%\" >nul
        echo [5/5] Installer done
    ) else (
        echo [WARN] NSIS build failed
    )
)

:end
echo ========================================
echo Build complete!
echo Output: %BUILD_DIR%
dir /B "%BUILD_DIR%"
echo ========================================
pause
