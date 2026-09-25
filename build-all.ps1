$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

Write-Host ""
Write-Host "=== RA2 ALL-IN-ONE BUILD ===" -ForegroundColor Cyan
Write-Host "Project: $root"
Write-Host ""

$modsDir = Join-Path $root "mods"
$inputDir = Join-Path $root "input"
$outputDir = Join-Path $root "output"
$webDir = Join-Path $root "redalert2"

New-Item -ItemType Directory -Force $modsDir | Out-Null
New-Item -ItemType Directory -Force $inputDir | Out-Null
New-Item -ItemType Directory -Force $outputDir | Out-Null

$shell = Join-Path $inputDir "RA2-shell-unsigned.ipa"
$base = Join-Path $inputDir "RA2-YR-FULL-unsigned.ipa"

if (-not (Test-Path $shell)) {
    throw "Missing: $shell"
}
if (-not (Test-Path $base)) {
    throw "Missing: $base"
}

$allModDirs = Get-ChildItem $modsDir -Directory | Sort-Object Name
$mods = @($allModDirs | Where-Object { Test-Path (Join-Path $_.FullName "modcd.ini") })
$workDirs = @($allModDirs | Where-Object { -not (Test-Path (Join-Path $_.FullName "modcd.ini")) })

if ($workDirs.Count -gt 0) {
    Write-Host "Work/unprepared folders (skipped):" -ForegroundColor DarkYellow
    $workDirs | ForEach-Object { Write-Host "  - $($_.Name)" }
    Write-Host ""
}

if ($mods.Count -eq 0) {
    throw "No prepared mods with modcd.ini found in $modsDir"
}

Write-Host "Mods to package:" -ForegroundColor Yellow
$mods | ForEach-Object { Write-Host "  - $($_.Name)" }
Write-Host ""

if (-not (Get-Command bun -ErrorAction SilentlyContinue)) {
    $bunPath = Join-Path $env:USERPROFILE ".bun\bin"
    $env:Path += ";$bunPath"
}

Push-Location $webDir
try {
    Write-Host "[1/2] Building WebDist..." -ForegroundColor Cyan
    bun --bun vite build
    if ($LASTEXITCODE -ne 0) {
        throw "Vite build failed."
    }
}
finally {
    Pop-Location
}

Write-Host ""
Write-Host "[2/2] Packaging IPA..." -ForegroundColor Cyan

python ".\build-ra2-all-in-one.py"

if ($LASTEXITCODE -ne 0) {
    throw "IPA packaging failed."
}

$final = Join-Path $outputDir "RA2-ALL-IN-ONE-FULL-unsigned.ipa"
if (-not (Test-Path $final)) {
    throw "Final IPA was not created: $final"
}

Write-Host ""
Write-Host "DONE" -ForegroundColor Green
Write-Host $final -ForegroundColor Green
