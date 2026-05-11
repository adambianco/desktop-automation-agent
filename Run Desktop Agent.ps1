# Desktop Automation Agent - Launcher
# Reads the Python path saved by install.ps1 and launches the app

$HERE = Split-Path -Parent $MyInvocation.MyCommand.Path
$pathFile = Join-Path $HERE "python_path.txt"
$launchPy = Join-Path $HERE "desktop_agent\launch.py"

# Also check if launch.py is in the same folder (in case run from inside desktop_agent)
if (-not (Test-Path $launchPy)) {
    $launchPy = Join-Path $HERE "launch.py"
}

# ── Find Python ───────────────────────────────────────────────────────────────
$pythonExe = $null

# 1. Read saved path from install.ps1
if (Test-Path $pathFile) {
    $saved = (Get-Content $pathFile -Raw).Trim()
    if (Test-Path $saved) {
        $pythonExe = $saved
    }
}

# 2. Search AppData\Local\Python (handles pythoncore-3.14-64 and any other naming)
if (-not $pythonExe) {
    $found = Get-ChildItem -Path "$env:LOCALAPPDATA\Python" -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue -Depth 3 |
             Where-Object { $_.FullName -notlike "*WindowsApps*" } |
             Select-Object -First 1
    if ($found) { $pythonExe = $found.FullName }
}

# 3. Search AppData\Local\Programs\Python
if (-not $pythonExe) {
    $found = Get-ChildItem -Path "$env:LOCALAPPDATA\Programs\Python" -Filter "python.exe" -Recurse -ErrorAction SilentlyContinue -Depth 3 |
             Where-Object { $_.FullName -notlike "*WindowsApps*" } |
             Select-Object -First 1
    if ($found) { $pythonExe = $found.FullName }
}

if (-not $pythonExe) {
    Write-Host "Python not found. Please run install.bat first." -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

if (-not (Test-Path $launchPy)) {
    Write-Host "launch.py not found at: $launchPy" -ForegroundColor Red
    Write-Host "Make sure you are running this from inside the desktop_agent folder." -ForegroundColor Yellow
    Read-Host "Press Enter to exit"
    exit 1
}

Write-Host "Starting Desktop Automation Agent..." -ForegroundColor Cyan
Write-Host "Python: $pythonExe" -ForegroundColor DarkGray

# Save path for next time
$pythonExe | Out-File -FilePath $pathFile -Encoding ASCII -NoNewline

# Launch
Set-Location (Split-Path -Parent $launchPy)
& $pythonExe $launchPy
