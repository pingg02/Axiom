# Axiom launch quality gate (对标 DSH scripts/run-gates.ts)
# One command, shared by local pre-push and CI:
#   Python pytest + Java mvn test + frontend vitest/vite + version gate + secret gate.
#
# Usage:
#   .\scripts\verify_launch.ps1                # run every gate
#   .\scripts\verify_launch.ps1 -InstallDeps   # also pip install -e ".[dev]" + npm ci
#   .\scripts\verify_launch.ps1 -SkipJava      # skip one axis when you just verified it
#
# Exit code 0 only when every gate passed.

param(
    [switch]$InstallDeps,
    [switch]$SkipPython,
    [switch]$SkipJava,
    [switch]$SkipFrontend,
    [switch]$SkipAudit
)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$results = [System.Collections.Generic.List[object]]::new()
$failed = 0

function Invoke-GateStep([string]$Name, [scriptblock]$Body) {
    $previous = Get-Location
    Write-Host ""
    Write-Host "===== $Name ====="
    try {
        & $Body
        if ($LASTEXITCODE -ne 0) { throw "step exited with code $LASTEXITCODE" }
        $script:results.Add([pscustomobject]@{ Name = $Name; Ok = $true })
        Write-Host "[OK] $Name"
    } catch {
        $script:results.Add([pscustomobject]@{ Name = $Name; Ok = $false })
        $script:failed++
        Write-Host "[FAIL] $Name : $($_.Exception.Message)"
    } finally {
        Set-Location $previous
    }
}

function Get-PythonInvocation {
    # Prefer a local virtualenv so `verify_launch -InstallDeps` works on a
    # fresh clone. Otherwise fall back to the system interpreter:
    # AXIOM_BUILD_USE_PYTHON=1 forces the `python` on PATH (used by CI after
    # actions/setup-python) instead of the system `py` launcher.
    foreach ($venv in @("reasonix-py\.venv", "reasonix-py\venv")) {
        $candidate = Join-Path $root $venv
        $venvPython = Join-Path $candidate "Scripts\python.exe"
        if (Test-Path $venvPython) { return @($venvPython, @()) }
    }
    if ($env:AXIOM_BUILD_USE_PYTHON -eq "1") {
        $cmd = Get-Command "python" -ErrorAction SilentlyContinue
        if (-not $cmd) { throw "python not found (AXIOM_BUILD_USE_PYTHON=1)" }
        return @($cmd.Source, @())
    }
    $launcher = Get-Command "py" -ErrorAction SilentlyContinue
    if ($launcher) { return @($launcher.Source, @("-3")) }
    $cmd = Get-Command "python" -ErrorAction SilentlyContinue
    if (-not $cmd) { throw "python not found" }
    return @($cmd.Source, @())
}

function Invoke-Python([string[]]$Arguments, [string]$WorkingDirectory) {
    $py = Get-PythonInvocation
    Push-Location $WorkingDirectory
    try {
        & $py[0] @($py[1] + $Arguments)
    } finally {
        Pop-Location
    }
}

# ── Version + secret + contract gates ────────────────────────────────────────
Invoke-GateStep "Version consistency" {
    Invoke-Python @((Join-Path $root "scripts\verify_versions.py")) $root
}

Invoke-GateStep "Secret scan" {
    Invoke-Python @((Join-Path $root "scripts\scan_secrets.py")) $root
}

Invoke-GateStep "gRPC contract (pb2 vs security.proto)" {
    Invoke-Python @((Join-Path $root "scripts\verify_proto_contract.py")) $root
}

# ── Dependency audits ────────────────────────────────────────────────────────
if (-not $SkipAudit) {
    Invoke-GateStep "Python dependency audit (pip-audit)" {
        $py = Get-PythonInvocation
        if ($InstallDeps) {
            Invoke-Python @("-m", "pip", "install", "-q", "pip-audit") (Join-Path $root "reasonix-py")
        }
        Invoke-Python @("-m", "pip_audit", "--skip-editable") (Join-Path $root "reasonix-py")
    }

    Invoke-GateStep "Frontend npm audit" {
        Push-Location (Join-Path $root "desktop\python-frontend")
        try {
            npm audit --audit-level=moderate
        } finally {
            Pop-Location
        }
    }

    Invoke-GateStep "Electron npm audit" {
        Push-Location (Join-Path $root "desktop\electron")
        try {
            npm audit --audit-level=moderate
        } finally {
            Pop-Location
        }
    }
}

# ── Python ───────────────────────────────────────────────────────────────────
if (-not $SkipPython) {
    Invoke-GateStep "Python tests" {
        $py = Get-PythonInvocation
        if ($InstallDeps) {
            Invoke-Python @("-m", "pip", "install", "-q", "-e", ".[dev]") (Join-Path $root "reasonix-py")
        }
        Invoke-Python @("-m", "pytest", "-q") (Join-Path $root "reasonix-py")
    }
}

# ── Java ─────────────────────────────────────────────────────────────────────
if (-not $SkipJava) {
    Invoke-GateStep "Java tests" {
        Push-Location (Join-Path $root "reasonix-java")
        try {
            & ".\mvnw.cmd" test -q
        } finally {
            Pop-Location
        }
    }
}

# ── Frontend ─────────────────────────────────────────────────────────────────
if (-not $SkipFrontend) {
    Invoke-GateStep "Frontend tests + build" {
        Push-Location (Join-Path $root "desktop\python-frontend")
        try {
            if ($InstallDeps) {
                npm ci
                if ($LASTEXITCODE -ne 0) { throw "npm ci failed" }
            }
            npx vitest run --pool=forks --maxWorkers=1 --no-file-parallelism
            if ($LASTEXITCODE -ne 0) { throw "vitest failed" }
            npm run build
            if ($LASTEXITCODE -ne 0) { throw "vite build failed" }
        } finally {
            Pop-Location
        }
    }
}

# ── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "===== SUMMARY ====="
foreach ($result in $results) {
    Write-Host ("  [{0}] {1}" -f ($(if ($result.Ok) { "PASS" } else { "FAIL" })), $result.Name)
}
if ($failed -gt 0) {
    Write-Host "[GATE] $failed step(s) failed"
    exit 1
}
Write-Host "[GATE] all checks passed"
exit 0
