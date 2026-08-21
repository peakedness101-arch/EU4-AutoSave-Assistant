$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$ToolsRoot = Join-Path $ProjectRoot '.tools'
$RakalyDirectory = Join-Path $ToolsRoot 'rakaly-0.8.19'
$Rakaly = Join-Path $RakalyDirectory 'rakaly.exe'
$Archive = Join-Path $ToolsRoot 'rakaly-0.8.19-x86_64-pc-windows-msvc.zip'
$Url = 'https://github.com/rakaly/cli/releases/download/v0.8.19/rakaly-0.8.19-x86_64-pc-windows-msvc.zip'
$ExpectedArchiveSha256 = '343E2C33869B1EC82E4AB018D1BB6936CC68B63146F99F426939F4D76106710D'
$ExpectedExecutableSha256 = 'E154AF990AAED2C2F44284946772188C9749AD3F6B641B41F6C23456A6F1633D'

if (Test-Path -LiteralPath $Rakaly) {
    $ActualExecutableSha256 = (Get-FileHash -LiteralPath $Rakaly -Algorithm SHA256).Hash
    if ($ActualExecutableSha256 -ne $ExpectedExecutableSha256) {
        throw "Rakaly executable checksum mismatch. Expected $ExpectedExecutableSha256, got $ActualExecutableSha256."
    }
    Write-Output $Rakaly
    exit 0
}

New-Item -ItemType Directory -Path $ToolsRoot, $RakalyDirectory -Force | Out-Null
if (-not (Test-Path -LiteralPath $Archive)) {
    Write-Host 'Downloading verified Rakaly CLI 0.8.19...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Archive -UseBasicParsing
}

$ActualArchiveSha256 = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
if ($ActualArchiveSha256 -ne $ExpectedArchiveSha256) {
    throw "Rakaly archive checksum mismatch. Expected $ExpectedArchiveSha256, got $ActualArchiveSha256."
}

Expand-Archive -LiteralPath $Archive -DestinationPath $RakalyDirectory -Force
if (-not (Test-Path -LiteralPath $Rakaly)) {
    $Extracted = Get-ChildItem -LiteralPath $RakalyDirectory -Recurse -File -Filter 'rakaly.exe' |
        Select-Object -First 1
    if ($null -eq $Extracted) {
        throw "Rakaly extraction did not create $Rakaly"
    }
    Copy-Item -LiteralPath $Extracted.FullName -Destination $Rakaly -Force
}

$ActualExecutableSha256 = (Get-FileHash -LiteralPath $Rakaly -Algorithm SHA256).Hash
if ($ActualExecutableSha256 -ne $ExpectedExecutableSha256) {
    throw "Rakaly executable checksum mismatch. Expected $ExpectedExecutableSha256, got $ActualExecutableSha256."
}
Write-Output $Rakaly
