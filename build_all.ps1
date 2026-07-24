# Axiom Build Script (PowerShell)
# Build: Python exe + Java fatjar + frontend + desktop shell + launchers
# Usage:  .\build_all.ps1
# Output: reasonix-build\ (next to this script)

$ErrorActionPreference = "Stop"
$FINAL_BUILD_DIR = Join-Path $PSScriptRoot "reasonix-build"
$BUILD_DIR = Join-Path $PSScriptRoot "reasonix-build.tmp"
$BUILD_CACHE_DIR = Join-Path $PSScriptRoot ".build-cache"
$SRC = $PSScriptRoot

function Assert-WorkspacePath([string]$TargetPath) {
    $root = [System.IO.Path]::GetFullPath($PSScriptRoot) + [System.IO.Path]::DirectorySeparatorChar
    $resolved = [System.IO.Path]::GetFullPath($TargetPath)
    if (-not $resolved.StartsWith($root, [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Build path escapes the workspace: $resolved"
    }
}

Assert-WorkspacePath $FINAL_BUILD_DIR
Assert-WorkspacePath $BUILD_DIR
Assert-WorkspacePath $BUILD_CACHE_DIR
New-Item -ItemType Directory -Path $BUILD_CACHE_DIR -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $BUILD_CACHE_DIR "temp") -Force | Out-Null
$env:PIP_CACHE_DIR = Join-Path $BUILD_CACHE_DIR "pip"
$env:npm_config_cache = Join-Path $BUILD_CACHE_DIR "npm"
$env:ELECTRON_CACHE = Join-Path $BUILD_CACHE_DIR "electron"
$env:ELECTRON_BUILDER_CACHE = Join-Path $BUILD_CACHE_DIR "electron-builder"
$env:TEMP = Join-Path $BUILD_CACHE_DIR "temp"
$env:TMP = $env:TEMP

Write-Host "========================================"
Write-Host "Axiom Build Script"
Write-Host "Output: $FINAL_BUILD_DIR"
Write-Host "========================================"

# Clean and create temporary output dir. The final build dir is replaced only
# after every required build step succeeds, so a failed build does not erase the
# last runnable exe.
if (Test-Path $BUILD_DIR) { Remove-Item -Recurse -Force $BUILD_DIR }
New-Item -ItemType Directory -Path $BUILD_DIR -Force | Out-Null

# Step 1: Build Python exe
Write-Host "[1/6] Building Python exe..."
Set-Location (Join-Path $SRC "reasonix-py")
python -m pip install -e . pyinstaller
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] pip install failed"; exit 1 }
python -m PyInstaller reasonix_min.spec
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] PyInstaller failed"; exit 1 }
if (-not (Test-Path "dist\reasonix.exe")) { Write-Host "[ERROR] PyInstaller did not produce dist\reasonix.exe"; exit 1 }
Copy-Item "dist\reasonix.exe" -Destination $BUILD_DIR -Force
& (Join-Path $BUILD_DIR "reasonix.exe") --version
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Built reasonix.exe failed smoke test"; exit 1 }
Write-Host "[1/6] Python exe done"

# Step 2: Build Java fatjar
Write-Host "[2/6] Building Java fatjar..."
Set-Location (Join-Path $SRC "reasonix-java")
& ".\mvnw.cmd" package -DskipTests
if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Maven failed"; exit 1 }

$jarDir = Join-Path $BUILD_DIR "reasonix-java" | Join-Path -Child "target"
New-Item -ItemType Directory -Path $jarDir -Force | Out-Null
if (-not (Test-Path "target\reasonix-security.jar")) { Write-Host "[ERROR] Maven did not produce target\reasonix-security.jar"; exit 1 }
Copy-Item "target\reasonix-security.jar" -Destination $jarDir -Force
Write-Host "[2/6] Java fatjar done"

# Step 3: Build frontend
Write-Host "[3/6] Building frontend..."
$node = Get-Command "node" -ErrorAction SilentlyContinue
if (-not $node) {
    Write-Host "[SKIP] Node.js not found"
} else {
    Set-Location (Join-Path $SRC "desktop\python-frontend")
    npm install
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] npm install failed"; exit 1 }
    npm run build
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] npm run build failed"; exit 1 }
    $frontendDir = Join-Path $BUILD_DIR "frontend"
    New-Item -ItemType Directory -Path $frontendDir -Force | Out-Null
    Copy-Item -Recurse "dist\*" -Destination $frontendDir -Force
    $electronFrontendDir = Join-Path $SRC "desktop\electron\frontend"
    Assert-WorkspacePath $electronFrontendDir
    if (Test-Path $electronFrontendDir) { Remove-Item -Recurse -Force $electronFrontendDir }
    New-Item -ItemType Directory -Path $electronFrontendDir -Force | Out-Null
    Copy-Item -Recurse "dist\*" -Destination $electronFrontendDir -Force
    Write-Host "[3/6] Frontend done"
}

# Step 4: Copy launchers
Write-Host "[4/6] Copying launchers..."
Copy-Item (Join-Path $SRC "start_reasonix_full.cmd") -Destination $BUILD_DIR -Force
Copy-Item (Join-Path $SRC "start_reasonix.cmd") -Destination $BUILD_DIR -Force
Copy-Item (Join-Path $SRC "start_reasonix_desktop.cmd") -Destination $BUILD_DIR -Force
Write-Host "[4/6] Launchers copied"

# Step 5: Build Electron desktop shell
Write-Host "[5/6] Building Electron desktop shell..."
$electronDir = Join-Path $SRC "desktop\electron"
if (-not $node) {
    Write-Host "[SKIP] Node.js not found"
} elseif (-not (Test-Path (Join-Path $electronDir "package.json"))) {
    Write-Host "[SKIP] Electron package not found"
} else {
    Set-Location $electronDir
    $electronReleaseDir = Join-Path $electronDir "release"
    Assert-WorkspacePath $electronReleaseDir
    if (Test-Path $electronReleaseDir) {
        Remove-Item -LiteralPath $electronReleaseDir -Recurse -Force
    }
    npm install
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Electron npm install failed"; exit 1 }
    npm run build
    if ($LASTEXITCODE -ne 0) { Write-Host "[ERROR] Electron build failed"; exit 1 }
    $electronOut = Join-Path $BUILD_DIR "desktop-electron"
    New-Item -ItemType Directory -Path $electronOut -Force | Out-Null
    Copy-Item -Recurse "release\*" -Destination $electronOut -Force
    Write-Host "[5/6] Electron desktop shell done"
}

# Step 6: Build legacy NSIS installer
Write-Host "[6/6] Building legacy installer..."
$makensis = Get-Command "makensis" -ErrorAction SilentlyContinue
if (-not $makensis) {
    Write-Host "[SKIP] NSIS not found"
} else {
    Set-Location (Join-Path $SRC "desktop")
    & "makensis" "installer.nsi"
    if ($LASTEXITCODE -eq 0) {
        Copy-Item "Reasonix-windows-amd64-installer.exe" -Destination $BUILD_DIR -Force
        Write-Host "[6/6] Installer done"
    } else { Write-Host "[WARN] NSIS build failed" }
}

Write-Host "========================================"
Write-Host "Build complete!"
try {
    if (Test-Path $FINAL_BUILD_DIR) { Remove-Item -Recurse -Force $FINAL_BUILD_DIR }
    Move-Item -Path $BUILD_DIR -Destination $FINAL_BUILD_DIR
    $publishedBuildDir = $FINAL_BUILD_DIR
} catch {
    $publishedBuildDir = $BUILD_DIR
    Write-Host "[WARN] Could not replace $FINAL_BUILD_DIR"
    Write-Host "[WARN] A previous executable may still be running and locking files."
    Write-Host "[WARN] Fresh build left at: $publishedBuildDir"
}
$files = Get-ChildItem $publishedBuildDir -Recurse -File | Where-Object { $_.Name -notlike "node_modules*" }
foreach ($f in $files) { Write-Host "  $($f.Name) - $($f.Length) bytes" }
$jarPath = Join-Path $publishedBuildDir "reasonix-java\target\reasonix-security.jar"
if (-not (Test-Path $jarPath)) { Write-Host "[NOTE] Java fatjar not found (Maven may have failed)" }
if (-not (Get-Command "node" -ErrorAction SilentlyContinue)) { Write-Host "[NOTE] Frontend skipped (Node.js not available)" }
if (-not (Get-Command "makensis" -ErrorAction SilentlyContinue)) { Write-Host "[NOTE] Installer skipped (NSIS not available)" }
