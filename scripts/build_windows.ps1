$ErrorActionPreference = "Stop"

$Root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $Root

if (-not (Test-Path ".venv")) {
    python -m venv .venv
}

& ".\.venv\Scripts\Activate.ps1"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

python -m PyInstaller `
    --noconfirm `
    --clean `
    --windowed `
    --onefile `
    --name PDFDiffStudio `
    --paths src `
    src\pdfdiffstudio\__main__.py

Write-Host ""
Write-Host "Portable executable created at: dist\PDFDiffStudio.exe"
