# Desktop Automation Agent - Installer
# Run by double-clicking install.bat

$ErrorActionPreference = "Continue"
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Desktop Automation Agent - Installer" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Folder: $HERE"
Write-Host ""

# ── Find Python ───────────────────────────────────────────────────────────────
Write-Host "Searching for Python..." -ForegroundColor Yellow
$pythonExe = $null

# Search all likely locations — handles pythoncore-3.14-64 and any other naming
$searchPaths = @(
    "$env:LOCALAPPDATA\Python",
    "$env:LOCALAPPDATA\Programs\Python",
    "$env:ProgramFiles",
    "$env:ProgramW6432",
    "C:\"
) | Where-Object { $_ -and (Test-Path $_) }

foreach ($root in $searchPaths) {
    if ($pythonExe) { break }
    $found = Get-ChildItem -Path $root -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue -Depth 5 |
             Where-Object { $_.FullName -notlike "*WindowsApps*" } |
             Select-Object -First 1
    if ($found) {
        $pythonExe = $found.FullName
        Write-Host "[FOUND] $pythonExe" -ForegroundColor Green
    }
}

if (-not $pythonExe) {
    Write-Host ""
    Write-Host "ERROR: Python not found." -ForegroundColor Red
    Write-Host "Install from: https://www.python.org/downloads/" -ForegroundColor Yellow
    Write-Host "During install, check 'Add Python to PATH'" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "[OK] Python: $pythonExe" -ForegroundColor Green
& $pythonExe --version
Write-Host ""

# Save path so launcher never needs to search again
$pythonExe | Out-File -FilePath "$HERE\python_path.txt" -Encoding ASCII -NoNewline
Write-Host "[OK] Path saved to python_path.txt" -ForegroundColor Green
Write-Host ""

# ── Check version ─────────────────────────────────────────────────────────────
& $pythonExe -c "import sys; exit(0 if sys.version_info>=(3,8) else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "ERROR: Python 3.8+ required." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

# ── Upgrade pip ───────────────────────────────────────────────────────────────
Write-Host "Upgrading pip..." -ForegroundColor Yellow
& $pythonExe -m pip install --upgrade pip --quiet
Write-Host "[OK] pip ready." -ForegroundColor Green
Write-Host ""

# ── Install packages ──────────────────────────────────────────────────────────
Write-Host "Installing packages (1-3 minutes on first run)..." -ForegroundColor Yellow
Write-Host ""
& $pythonExe -m pip install -r "$HERE\desktop_agent\requirements.txt"

if ($LASTEXITCODE -ne 0) {
    # Try from same directory
    & $pythonExe -m pip install -r "$HERE\requirements.txt"
}

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "ERROR: Package installation failed." -ForegroundColor Red
    Write-Host "Try right-clicking install.bat and choosing 'Run as administrator'" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "[OK] All packages installed." -ForegroundColor Green
Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Installation Complete!" -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Double-click 'Run Desktop Agent.bat' to open the app." -ForegroundColor Green
Write-Host ""
Read-Host "Press Enter to close"
