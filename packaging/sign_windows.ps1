#Requires -Version 5.1
<#
  Подпись exe и установщика (Authenticode). Без сертификата — пропуск.

  Локально:
    $env:WINDOWS_SIGN_PFX_PATH = "C:\certs\bpmind.pfx"
    $env:WINDOWS_SIGN_PFX_PASSWORD = "secret"
    .\packaging\sign_windows.ps1 -Version 1.8.0-beta.1

  CI (GitHub Secrets):
    WINDOWS_SIGN_PFX_B64 — base64 содержимого .pfx
    WINDOWS_SIGN_PFX_PASSWORD
#>
param(
  [string]$Version = "0.0.0-dev"
)

$ErrorActionPreference = "Stop"
$RepoRoot = Split-Path -Parent $PSScriptRoot
$Dist = Join-Path $RepoRoot "dist"

$Signtool = @(
  "${env:ProgramFiles(x86)}\Windows Kits\10\bin\*\x64\signtool.exe",
  "${env:ProgramFiles}\Windows Kits\10\bin\*\x64\signtool.exe"
) | ForEach-Object { Get-Item $_ -ErrorAction SilentlyContinue } | Sort-Object FullName -Descending | Select-Object -First 1

if (-not $Signtool) {
  Write-Warning "signtool.exe не найден (Windows SDK). Подпись пропущена."
  exit 0
}

$PfxPath = $env:WINDOWS_SIGN_PFX_PATH
$PfxPassword = $env:WINDOWS_SIGN_PFX_PASSWORD

if ($env:WINDOWS_SIGN_PFX_B64) {
  $PfxPath = Join-Path $env:RUNNER_TEMP "sign.pfx"
  [IO.File]::WriteAllBytes($PfxPath, [Convert]::FromBase64String($env:WINDOWS_SIGN_PFX_B64))
}

if (-not $PfxPath -or -not (Test-Path $PfxPath)) {
  Write-Warning "Сертификат не задан (WINDOWS_SIGN_PFX_PATH / WINDOWS_SIGN_PFX_B64). Подпись пропущена."
  exit 0
}

$Targets = @(
  (Join-Path $Dist "BPMind Auto Mixer\BPMind Auto Mixer.exe"),
  (Join-Path $Dist "BPMind-Auto-Mixer-Windows-setup-$Version.exe")
) | Where-Object { Test-Path $_ }

if ($Targets.Count -eq 0) {
  Write-Warning "Нет файлов для подписи в dist\"
  exit 0
}

$Timestamp = "http://timestamp.digicert.com"
foreach ($file in $Targets) {
  Write-Host "Подпись: $file"
  & $Signtool.FullName sign /fd SHA256 /tr $Timestamp /td SHA256 /f $PfxPath /p $PfxPassword $file
  & $Signtool.FullName verify /pa $file
}

Write-Host "Подпись завершена."
