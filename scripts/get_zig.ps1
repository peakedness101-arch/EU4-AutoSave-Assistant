$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$ToolsRoot = Join-Path $ProjectRoot '.tools'
$ZigDirectory = Join-Path $ToolsRoot 'zig-windows-x86_64-0.13.0'
$Zig = Join-Path $ZigDirectory 'zig.exe'
$Archive = Join-Path $ToolsRoot 'zig-windows-x86_64-0.13.0.zip'
$Url = 'https://ziglang.org/download/0.13.0/zig-windows-x86_64-0.13.0.zip'
$ExpectedSha256 = 'D859994725EF9402381E557C60BB57497215682E355204D754EE3DF75EE3C158'

if (Test-Path -LiteralPath $Zig) {
    Write-Output $Zig
    exit 0
}

New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
if (-not (Test-Path -LiteralPath $Archive)) {
    Write-Host 'Downloading verified Zig 0.13.0 toolchain...'
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $Url -OutFile $Archive -UseBasicParsing
}

$ActualSha256 = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
if ($ActualSha256 -ne $ExpectedSha256) {
    throw "Zig archive checksum mismatch. Expected $ExpectedSha256, got $ActualSha256."
}

Expand-Archive -LiteralPath $Archive -DestinationPath $ToolsRoot
if (-not (Test-Path -LiteralPath $Zig)) {
    throw "Zig extraction did not create $Zig"
}
Write-Output $Zig

