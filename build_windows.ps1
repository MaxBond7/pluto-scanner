# Build a portable one-folder Windows distribution and release artifacts.
#
#   .\build_windows.ps1
#   .\build_windows.ps1 -Clean
#   .\build_windows.ps1 -Clean -Installer
#   .\build_windows.ps1 -SkipTests
#
# Result:
#   dist\SDRScanner\SDRScanner.exe
#   dist\SDRScanner-<version>-portable.zip
#   dist\SHA256SUMS.txt
#   dist\SDRScanner-Setup-<version>.exe   (with -Installer and Inno Setup)
param(
    [switch]$Clean,
    [switch]$SkipTests,
    [switch]$SkipZip,
    [switch]$Installer
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

$pyproject = Get-Content (Join-Path $root "pyproject.toml") -Raw
if ($pyproject -notmatch '(?m)^version\s*=\s*"([^"]+)"') {
    throw "Не удалось прочитать версию из pyproject.toml"
}
$version = $Matches[1]
$initText = Get-Content (Join-Path $root "sdr_scanner\__init__.py") -Raw
if ($initText -notmatch '__version__\s*=\s*"([^"]+)"') {
    throw "Не удалось прочитать __version__"
}
if ($version -ne $Matches[1]) {
    throw "Версии не совпадают: pyproject=$version, __init__=$($Matches[1])"
}
Write-Host "== SDR Scanner $version =="

# The exe version resource is generated, not hand-maintained: a stale version
# in the binary looks sloppy and helps nobody (and Windows shows it in the
# file properties and in Defender's file details).
$parts = $version.Split(".")
while ($parts.Count -lt 4) { $parts += "0" }
$quad = ($parts[0..3] -join ", ")
$versionInfo = @"
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=($quad),
    prodvers=($quad),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          u'040904B0',
          [
            StringStruct(u'CompanyName', u'SDR Scanner contributors'),
            StringStruct(u'FileDescription', u'SDR Scanner - SDR spectrum and drone-band monitor'),
            StringStruct(u'FileVersion', u'$version'),
            StringStruct(u'InternalName', u'SDRScanner'),
            StringStruct(u'LegalCopyright', u'GPL-3.0-only'),
            StringStruct(u'OriginalFilename', u'SDRScanner.exe'),
            StringStruct(u'ProductName', u'SDR Scanner'),
            StringStruct(u'ProductVersion', u'$version')
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct(u'Translation', [1033, 1200])])
  ]
)
"@
Set-Content -Path (Join-Path $root "packaging\version_info.txt") `
    -Value $versionInfo -Encoding UTF8

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
& $python -m PyInstaller packaging\sdr_scanner.spec --noconfirm
$code = $LASTEXITCODE
$ErrorActionPreference = $previous
if ($code -ne 0) {
    throw "PyInstaller завершился с ошибкой."
}

$appDir = Join-Path $root "dist\SDRScanner"
$exe = Join-Path $appDir "SDRScanner.exe"
if (-not (Test-Path $exe)) {
    throw "Сборка не создала $exe"
}

# Portable mode: data stays next to the executable.  The installer excludes
# this file, so an installed build uses %LOCALAPPDATA%\SDRScanner instead.
Set-Content -Path (Join-Path $appDir "portable.flag") `
    -Value "portable" -Encoding ascii

# Keep documentation and licensing next to the executable.
foreach ($name in @("LICENSE", "THIRD_PARTY_NOTICES.md", "README.md", "CHANGELOG.md")) {
    $source = Join-Path $root $name
    if (Test-Path $source) {
        $targetName = if ($name -eq "LICENSE") { "LICENSE.txt" } else { $name }
        Copy-Item $source (Join-Path $appDir $targetName) -Force
    }
}

$artifacts = @($exe)
if (-not $SkipZip) {
    $zip = Join-Path $root "dist\SDRScanner-$version-portable.zip"
    if (Test-Path $zip) {
        Remove-Item $zip -Force
    }
    Write-Host "== ZIP =="
    Compress-Archive -Path $appDir -DestinationPath $zip -CompressionLevel Optimal
    $artifacts += $zip
}

if ($Installer) {
    Write-Host "== Inno Setup =="
    $iscc = Get-Command iscc -ErrorAction SilentlyContinue
    if ($null -eq $iscc) {
        foreach ($candidate in @(
            "C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
            "C:\Program Files\Inno Setup 6\ISCC.exe",
            (Join-Path $env:LOCALAPPDATA "Programs\Inno Setup 6\ISCC.exe")
        )) {
            if (Test-Path $candidate) {
                $iscc = Get-Item $candidate
                break
            }
        }
    }
    if ($null -eq $iscc) {
        Write-Warning "Inno Setup не найден: установщик пропущен."
    } else {
        $isccPath = if ($iscc.Source) { $iscc.Source } else { $iscc.FullName }
        & $isccPath "/DMyAppVersion=$version" `
            (Join-Path $root "installer\sdr_scanner.iss")
        if ($LASTEXITCODE -ne 0) {
            throw "Inno Setup завершился с ошибкой."
        }
        $setup = Join-Path $root "dist\SDRScanner-Setup-$version.exe"
        if (Test-Path $setup) {
            $artifacts += $setup
        }
    }
}

$hashLines = foreach ($file in $artifacts) {
    if (Test-Path $file) {
        $hash = (Get-FileHash $file -Algorithm SHA256).Hash.ToLower()
        "$hash  $(Split-Path $file -Leaf)"
    }
}
$hashLines | Set-Content -Path (Join-Path $root "dist\SHA256SUMS.txt") -Encoding ascii

$size = (Get-ChildItem $appDir -Recurse -File |
    Measure-Object Length -Sum).Sum
Write-Host ""
Write-Host "Готово: $exe"
Write-Host ("Размер one-folder: {0:N0} МБ" -f ($size / 1MB))
Write-Host "Артефакты:"
foreach ($file in $artifacts) {
    if (Test-Path $file) {
        Write-Host ("  {0}" -f (Split-Path $file -Leaf))
    }
}
Write-Host "Портативные данные: рядом с .exe; установленная версия: %LOCALAPPDATA%\SDRScanner"
