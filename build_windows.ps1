# Build a portable one-folder Windows distribution.
#
#   .\build_windows.ps1
#   .\build_windows.ps1 -Clean
#   .\build_windows.ps1 -SkipTests
#
# Result: dist\PlutoScanner\PlutoScanner.exe
param(
    [switch]$Clean,
    [switch]$SkipTests
)

try {
    [Console]::OutputEncoding = [System.Text.Encoding]::UTF8
} catch {
}
$OutputEncoding = [System.Text.Encoding]::UTF8

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$python = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $python)) {
    throw "Не найден $python. Создайте окружение и установите зависимости."
}

if (-not $SkipTests) {
    Write-Host "== Тесты =="
    & $python -m pytest -q
    if ($LASTEXITCODE -ne 0) {
        throw "Тесты не прошли, сборка остановлена."
    }
}

if ($Clean) {
    Write-Host "== Очистка build/ и dist/ =="
    Remove-Item -Recurse -Force build, dist -ErrorAction SilentlyContinue
}

Write-Host "== PyInstaller (one-folder) =="
$previous = $ErrorActionPreference
$ErrorActionPreference = "Continue"  # PyInstaller logs to stderr
& $python -m PyInstaller packaging\pluto_scanner.spec --noconfirm
$code = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($code -ne 0) {
    throw "PyInstaller завершился с ошибкой."
}

$exe = Join-Path $root "dist\PlutoScanner\PlutoScanner.exe"
if (-not (Test-Path $exe)) {
    throw "Сборка не создала $exe"
}

# Keep licensing information next to the executable for redistribution.
Copy-Item (Join-Path $root "LICENSE") (Join-Path $root "dist\PlutoScanner\LICENSE.txt") -Force
Copy-Item (Join-Path $root "THIRD_PARTY_NOTICES.md") `
    (Join-Path $root "dist\PlutoScanner\THIRD_PARTY_NOTICES.md") -Force

$size = (Get-ChildItem (Join-Path $root "dist\PlutoScanner") -Recurse -File |
    Measure-Object Length -Sum).Sum
Write-Host ""
Write-Host "Готово: $exe"
Write-Host ("Размер: {0:N0} МБ" -f ($size / 1MB))
Write-Host "Данные пользователя будут созданы рядом с .exe в user_data\."
