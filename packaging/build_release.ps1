#Requires -Version 5.1
param(
  [string]$Version = "0.0.0-dev",
  [switch]$SkipTests,
  [switch]$Sign
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $RepoRoot

if (-not $SkipTests) {
  $env:PYTHONPATH = "."
  python -m pytest tests/ -q
}

pip install -q -r requirements.txt -r requirements-build.txt
python packaging/build_app_icon.py
pyinstaller packaging/bpmind.spec --noconfirm

$DistApp = Join-Path $RepoRoot "dist\BPMind Auto Mixer"
if (-not (Test-Path $DistApp)) {
  throw "Нет папки сборки: $DistApp"
}

$Iscc = @(
  "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
  "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1

if ($Iscc) {
  & $Iscc (Join-Path $PSScriptRoot "bpmind.iss") "/DMyAppVersion=$Version"
} else {
  Write-Warning "Inno Setup 6 не найден — setup.exe не собран."
}

if ($Sign) {
  & (Join-Path $PSScriptRoot "sign_windows.ps1") -Version $Version
}

Copy-Item (Join-Path $PSScriptRoot "portable.flag") (Join-Path $DistApp "portable.flag") -Force
$PortableZip = Join-Path $RepoRoot "dist\BPMind-Auto-Mixer-Windows-portable.zip"
if (Test-Path $PortableZip) { Remove-Item $PortableZip -Force }
Compress-Archive -Path $DistApp -DestinationPath $PortableZip -Force

Write-Host "Portable: $PortableZip"
if ($Iscc) {
  Write-Host "Setup: dist\BPMind-Auto-Mixer-Windows-setup-$Version.exe"
}
Write-Host "Готово."
