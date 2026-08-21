param(
    [string]$ReleaseVersion = '1.2'
)

$ErrorActionPreference = 'Stop'

$Workspace = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Python = Join-Path $Workspace '.venv\Scripts\python.exe'
$BuildRoot = Join-Path $Workspace 'build'
$DistributionRoot = Join-Path $Workspace 'dist'
$StagingRoot = Join-Path $BuildRoot 'release_staging'
$NativeBuildRoot = Join-Path $BuildRoot 'native_release'
$BundleName = "EU4_AutoSave_Assistant_Final_491d_$ReleaseVersion"
$StagedBundle = Join-Path $StagingRoot $BundleName
$StagedApp = Join-Path $StagedBundle 'release\EU4_AutoSave_Assistant'
$FinalBundle = Join-Path $DistributionRoot $BundleName
$ZipPath = Join-Path $DistributionRoot ($BundleName + '.zip')
$AppName = 'EU4_AutoSave_Assistant'
$MaximumReleaseBytes = 110MB
$RakalyLicense = Join-Path $Workspace 'licenses\Rakaly.txt'

function Assert-ChildPath([string]$Path, [string]$Parent) {
    $resolvedPath = [IO.Path]::GetFullPath($Path).TrimEnd([char]92)
    $resolvedParent = [IO.Path]::GetFullPath($Parent).TrimEnd([char]92) + '\'
    if (-not $resolvedPath.StartsWith($resolvedParent, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing operation outside expected directory: $resolvedPath"
    }
}

function Remove-ExactPath([string]$Path, [string]$Parent) {
    Assert-ChildPath $Path $Parent
    if (Test-Path -LiteralPath $Path) {
        Remove-Item -LiteralPath $Path -Recurse -Force
    }
}

if (-not (Test-Path -LiteralPath $Python)) {
    throw "Python environment is missing. Run scripts\setup.ps1 first: $Python"
}
foreach ($required in @(
    (Join-Path $Workspace 'native\bridge.cpp'),
    (Join-Path $Workspace 'native\injector.cpp'),
    (Join-Path $Workspace 'native\launcher.cpp'),
    (Join-Path $Workspace 'data\country_names.html'),
    $RakalyLicense
)) {
    if (-not (Test-Path -LiteralPath $required)) {
        throw "Required release input is missing: $required"
    }
}

New-Item -ItemType Directory -Path $BuildRoot, $DistributionRoot, $StagingRoot -Force | Out-Null
Remove-ExactPath $StagedBundle $StagingRoot
Remove-ExactPath $FinalBundle $DistributionRoot
if (Test-Path -LiteralPath $ZipPath) {
    Assert-ChildPath $ZipPath $DistributionRoot
    Remove-Item -LiteralPath $ZipPath -Force
}
New-Item -ItemType Directory -Path $StagedBundle | Out-Null

& (Join-Path $PSScriptRoot 'build_native.ps1') -OutputDirectory $NativeBuildRoot
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
$Rakaly = (& (Join-Path $PSScriptRoot 'get_rakaly.ps1') | Select-Object -Last 1)
if (-not (Test-Path -LiteralPath $Rakaly)) {
    throw "Verified Rakaly executable is missing: $Rakaly"
}

& $Python -m PyInstaller --noconfirm --clean --windowed `
    --name $AppName `
    --paths (Join-Path $Workspace 'src') `
    --distpath (Join-Path $StagedBundle 'release') `
    --workpath (Join-Path $BuildRoot 'pyinstaller') `
    --specpath $BuildRoot `
    --exclude-module PySide6.QtNetwork `
    --exclude-module PySide6.QtQml `
    --exclude-module PySide6.QtQuick `
    --exclude-module PySide6.QtQuickWidgets `
    --exclude-module PySide6.QtPdf `
    --exclude-module PySide6.QtPdfWidgets `
    --exclude-module PySide6.QtVirtualKeyboard `
    --exclude-module PIL.AvifImagePlugin `
    --exclude-module numpy.random `
    --exclude-module numpy.fft `
    (Join-Path $Workspace 'scripts\packaging_entry.py')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Internal = Join-Path $StagedApp '_internal'
$QtRoot = Join-Path $Internal 'PySide6'
foreach ($relative in @(
    'opengl32sw.dll', 'QtOpenGL.pyd', 'QtOpenGLWidgets.pyd',
    'Qt6Quick.dll', 'Qt6Qml.dll', 'Qt6Pdf.dll', 'Qt6QmlModels.dll',
    'Qt6VirtualKeyboard.dll', 'Qt6QmlMeta.dll', 'Qt6QmlWorkerScript.dll',
    'Qt6Network.dll', 'QtNetwork.pyd'
)) {
    Remove-ExactPath (Join-Path $QtRoot $relative) $StagedApp
}
foreach ($relative in @('libcrypto-3.dll', 'libssl-3.dll', 'libcrypto-3-x64.dll', 'libssl-3-x64.dll')) {
    Remove-ExactPath (Join-Path $Internal $relative) $StagedApp
}
foreach ($directory in @('random', 'fft')) {
    Remove-ExactPath (Join-Path $Internal ('numpy\' + $directory)) $StagedApp
}

$PluginRoot = Join-Path $QtRoot 'plugins'
foreach ($directory in @('generic', 'networkinformation', 'platforminputcontexts', 'tls')) {
    Remove-ExactPath (Join-Path $PluginRoot $directory) $StagedApp
}
$ImageFormats = Join-Path $PluginRoot 'imageformats'
if (Test-Path -LiteralPath $ImageFormats) {
    Get-ChildItem -LiteralPath $ImageFormats -File |
        Where-Object { $_.Name -notin @('qsvg.dll', 'qico.dll') } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}
$Platforms = Join-Path $PluginRoot 'platforms'
if (Test-Path -LiteralPath $Platforms) {
    Get-ChildItem -LiteralPath $Platforms -File |
        Where-Object { $_.Name -notin @('qwindows.dll', 'qoffscreen.dll') } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}
$Translations = Join-Path $QtRoot 'translations'
if (Test-Path -LiteralPath $Translations) {
    Get-ChildItem -LiteralPath $Translations -File |
        Where-Object { $_.Name -notmatch 'zh_CN' } |
        ForEach-Object { Remove-Item -LiteralPath $_.FullName -Force }
}

$NativeOutput = Join-Path $StagedApp 'native'
$DataOutput = Join-Path $StagedApp 'data'
New-Item -ItemType Directory -Path $NativeOutput, $DataOutput -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $NativeBuildRoot 'EU4AutoSaveBridge.dll') -Destination $NativeOutput
Copy-Item -LiteralPath (Join-Path $NativeBuildRoot 'EU4BridgeInjector.exe') -Destination $NativeOutput
Copy-Item -LiteralPath $Rakaly -Destination (Join-Path $NativeOutput 'rakaly.exe')
Copy-Item -LiteralPath $RakalyLicense -Destination (Join-Path $NativeOutput 'rakaly-LICENSE.txt')
@(
    'Rakaly CLI v0.8.19'
    'Source: https://github.com/rakaly/cli/releases/tag/v0.8.19'
    'Windows x64 executable SHA-256: E154AF990AAED2C2F44284946772188C9749AD3F6B641B41F6C23456A6F1633D'
) | Set-Content -LiteralPath (Join-Path $NativeOutput 'rakaly-VERSION.txt') -Encoding UTF8
if (Test-Path -LiteralPath (Join-Path $Workspace 'data\province_index.json')) {
    Copy-Item -LiteralPath (Join-Path $Workspace 'data\province_index.json') -Destination $DataOutput
}
if (Test-Path -LiteralPath (Join-Path $Workspace 'data\map_cache')) {
    Copy-Item -LiteralPath (Join-Path $Workspace 'data\map_cache') -Destination $DataOutput -Recurse
}
Copy-Item -LiteralPath (Join-Path $Workspace 'data\country_names.html') -Destination $DataOutput
Copy-Item -LiteralPath (Join-Path $Workspace 'README.md'),(Join-Path $Workspace '新用户使用指南.html') -Destination $StagedApp

Copy-Item -LiteralPath (Join-Path $NativeBuildRoot 'EU4AutoSaveLauncher.exe') -Destination (Join-Path $StagedBundle 'EU4_AutoSave_Assistant.exe')
Copy-Item -LiteralPath (Join-Path $Workspace 'README.md'),(Join-Path $Workspace '新用户使用指南.html'),(Join-Path $Workspace '版本说明.txt') -Destination $StagedBundle
Copy-Item -LiteralPath (Join-Path $Workspace 'data\country_names.html') -Destination (Join-Path $StagedBundle '国家列表.html')

$ReleaseBytes = (Get-ChildItem -LiteralPath $StagedApp -Recurse -File | Measure-Object Length -Sum).Sum
if ($ReleaseBytes -gt $MaximumReleaseBytes) {
    throw ('Release size {0:N2} MiB exceeds the {1:N0} MiB safety limit.' -f ($ReleaseBytes / 1MB), ($MaximumReleaseBytes / 1MB))
}

$env:QT_QPA_PLATFORM = 'offscreen'
$Smoke = Start-Process -FilePath (Join-Path $StagedApp "$AppName.exe") `
    -ArgumentList '--smoke-test' -WindowStyle Hidden -Wait -PassThru
if ($Smoke.ExitCode -ne 0) {
    throw "Staged release smoke test failed with exit code $($Smoke.ExitCode)."
}
if (-not (Test-Path -LiteralPath (Join-Path $StagedApp 'logs\assistant.log'))) {
    throw 'Staged release did not create its runtime log.'
}
foreach ($runtimePath in @(
    'logs', 'config', 'archives',
    'data\assistant.sqlite3', 'data\assistant.sqlite3-shm', 'data\assistant.sqlite3-wal'
)) {
    Remove-ExactPath (Join-Path $StagedApp $runtimePath) $StagedApp
}

$Manifest = [ordered]@{
    application = $AppName
    release = $ReleaseVersion
    required_build = '491d'
    generated_at = (Get-Date).ToString('o')
    size_bytes = [int64]$ReleaseBytes
    file_count = (Get-ChildItem -LiteralPath $StagedApp -Recurse -File).Count
    executable_sha256 = (Get-FileHash -LiteralPath (Join-Path $StagedApp "$AppName.exe") -Algorithm SHA256).Hash
    country_names = 978
}
$Manifest | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $StagedApp 'release_manifest.json') -Encoding UTF8

$Hashes = @(
    ('{0}  EU4_AutoSave_Assistant.exe' -f (Get-FileHash -LiteralPath (Join-Path $StagedBundle 'EU4_AutoSave_Assistant.exe') -Algorithm SHA256).Hash)
    ('{0}  release\EU4_AutoSave_Assistant\EU4_AutoSave_Assistant.exe' -f (Get-FileHash -LiteralPath (Join-Path $StagedApp 'EU4_AutoSave_Assistant.exe') -Algorithm SHA256).Hash)
    ('{0}  release\EU4_AutoSave_Assistant\native\rakaly.exe' -f (Get-FileHash -LiteralPath (Join-Path $NativeOutput 'rakaly.exe') -Algorithm SHA256).Hash)
    ('{0}  release\EU4_AutoSave_Assistant\data\country_names.html' -f (Get-FileHash -LiteralPath (Join-Path $DataOutput 'country_names.html') -Algorithm SHA256).Hash)
)
$Hashes | Set-Content -LiteralPath (Join-Path $StagedBundle 'SHA256SUMS.txt') -Encoding UTF8

Move-Item -LiteralPath $StagedBundle -Destination $FinalBundle
Add-Type -AssemblyName System.IO.Compression.FileSystem
[IO.Compression.ZipFile]::CreateFromDirectory(
    $FinalBundle,
    $ZipPath,
    [IO.Compression.CompressionLevel]::Optimal,
    $true
)

$ZipHash = (Get-FileHash -LiteralPath $ZipPath -Algorithm SHA256).Hash
Write-Host ('Release ready: {0:N2} MiB, {1} files' -f ($ReleaseBytes / 1MB), $Manifest.file_count)
Write-Host "Bundle: $FinalBundle"
Write-Host "ZIP: $ZipPath"
Write-Host "ZIP SHA256: $ZipHash"
