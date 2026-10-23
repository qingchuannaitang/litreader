# Build Litreader for Windows: dist\Litreader\Litreader.exe and dist\Litreader-<version>-win.zip
# Usage (PowerShell, in the litreader folder):  powershell -ExecutionPolicy Bypass -File scripts\build_win.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)
$ver = [regex]::Match((Get-Content src\litreader\__init__.py -Raw), '__version__ = "([^"]+)"').Groups[1].Value
if (-not $ver) { throw "version not found in src\litreader\__init__.py" }
$py = if ($env:PYTHON) { $env:PYTHON } else { "python" }
if (-not (Test-Path .venv-win)) { & $py -m venv .venv-win; if ($LASTEXITCODE) { throw "venv failed" } }
$vpy = ".venv-win\Scripts\python.exe"
& $vpy -m pip install --upgrade pip; if ($LASTEXITCODE) { throw "pip upgrade failed" }
& $vpy -m pip install -e ".[gui]" pyinstaller; if ($LASTEXITCODE) { throw "pip install failed" }
if (Test-Path build) { Remove-Item -Recurse -Force build }
if (Test-Path dist\Litreader) { Remove-Item -Recurse -Force dist\Litreader }
& $vpy -m PyInstaller --noconfirm --clean packaging\Litreader-win.spec; if ($LASTEXITCODE) { throw "PyInstaller failed" }
$zip = "dist\Litreader-$ver-win.zip"
if (Test-Path $zip) { Remove-Item -Force $zip }
Compress-Archive -Path dist\Litreader -DestinationPath $zip
Write-Host "Built $zip"
