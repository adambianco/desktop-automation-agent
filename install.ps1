# Desktop Automation Agent — Installer
# Double-click install.bat to run this.
# Finds Python, installs packages, creates a desktop shortcut, launches the app.

$ErrorActionPreference = "Continue"
$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host ""
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Desktop Automation Agent — Installing..." -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""

# ── Step 1: Find Python ───────────────────────────────────────────────────────
Write-Host "Looking for Python..." -ForegroundColor Yellow
$pythonExe = $null

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
        Write-Host "[OK] Python found: $pythonExe" -ForegroundColor Green
    }
}

if (-not $pythonExe) {
    Write-Host ""
    Write-Host "Python not found. Opening python.org/downloads in your browser..." -ForegroundColor Yellow
    Start-Process "https://www.python.org/downloads/"
    Write-Host ""
    Write-Host "Please install Python, then run this installer again." -ForegroundColor Yellow
    Write-Host "During install, check 'Add Python to PATH'" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

& $pythonExe --version
$pythonExe | Out-File -FilePath "$HERE\python_path.txt" -Encoding ASCII -NoNewline
Write-Host ""

# ── Step 2: Install packages ──────────────────────────────────────────────────
Write-Host "Installing required packages..." -ForegroundColor Yellow
Write-Host "(This takes 1-2 minutes on first run)" -ForegroundColor DarkGray
Write-Host ""

$reqFile = "$HERE\requirements.txt"
& $pythonExe -m pip install --upgrade pip --quiet
& $pythonExe -m pip install -r $reqFile

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "Package installation failed." -ForegroundColor Red
    Write-Host "Try right-clicking install.bat and choosing 'Run as administrator'" -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host ""
Write-Host "[OK] All packages installed." -ForegroundColor Green
Write-Host ""

# ── Step 3: Create Desktop Shortcut ──────────────────────────────────────────
Write-Host "Creating desktop shortcut..." -ForegroundColor Yellow

$launchScript = "$HERE\launch.py"
$shortcutPath = [System.IO.Path]::Combine(
    [System.Environment]::GetFolderPath("Desktop"),
    "Desktop Agent.lnk"
)

try {
    $WshShell = New-Object -ComObject WScript.Shell
    $shortcut = $WshShell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath    = $pythonExe
    $shortcut.Arguments     = "`"$launchScript`""
    $shortcut.WorkingDirectory = $HERE
    $shortcut.Description   = "Desktop Automation Agent"
    $shortcut.WindowStyle   = 1   # Normal window

    # Use Python's own icon if no custom icon available
    $shortcut.IconLocation  = "$pythonExe,0"

    $shortcut.Save()
    Write-Host "[OK] Shortcut created on your Desktop: 'Desktop Agent'" -ForegroundColor Green
} catch {
    Write-Host "[WARNING] Could not create shortcut: $_" -ForegroundColor Yellow
    Write-Host "You can still launch the app by double-clicking 'Run Desktop Agent.bat'" -ForegroundColor Yellow
}

Write-Host ""

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "  Installation Complete!" -ForegroundColor Green
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  A shortcut called 'Desktop Agent' has been added to your Desktop." -ForegroundColor White
Write-Host "  Double-click it any time to open the app." -ForegroundColor White
Write-Host ""
Write-Host "  Launching the app now..." -ForegroundColor Cyan
Write-Host ""

# ── Step 4: Launch the app ────────────────────────────────────────────────────
Start-Process $pythonExe -ArgumentList "`"$launchScript`"" -WorkingDirectory $HERE

# Keep window open briefly so user can read the success message
Start-Sleep -Seconds 3
