$ErrorActionPreference = 'Stop'

$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$ToolsRoot = Join-Path $ProjectRoot '.tools'
$ZigDirectory = Join-Path $ToolsRoot 'zig-windows-x86_64-0.13.0'
$Zig = Join-Path $ZigDirectory 'zig.exe'
$Archive = Join-Path $ToolsRoot 'zig-windows-x86_64-0.13.0.zip'
$PartialArchive = $Archive + '.partial'
$Url = 'https://ziglang.org/download/0.13.0/zig-windows-x86_64-0.13.0.zip'
$ExpectedSha256 = 'D859994725EF9402381E557C60BB57497215682E355204D754EE3DF75EE3C158'

function Remove-ToolPath([string]$Path) {
    $ResolvedPath = [IO.Path]::GetFullPath($Path)
    $ResolvedTools = [IO.Path]::GetFullPath($ToolsRoot).TrimEnd([char]92) + '\'
    if (-not $ResolvedPath.StartsWith($ResolvedTools, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to remove a path outside .tools: $ResolvedPath"
    }
    if (Test-Path -LiteralPath $ResolvedPath) {
        Remove-Item -LiteralPath $ResolvedPath -Recurse -Force
    }
}

if (Test-Path -LiteralPath $Zig) {
    Write-Output $Zig
    exit 0
}

New-Item -ItemType Directory -Path $ToolsRoot -Force | Out-Null
$ArchiveReady = $false
if (Test-Path -LiteralPath $Archive) {
    $ArchiveReady = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash -eq $ExpectedSha256
    if (-not $ArchiveReady) {
        Write-Warning 'Discarding an incomplete or unverified Zig archive.'
        Remove-ToolPath $Archive
    }
}
if (-not $ArchiveReady) {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    foreach ($Attempt in 1..3) {
        try {
            Remove-ToolPath $PartialArchive
            Write-Host "Downloading verified Zig 0.13.0 toolchain (attempt $Attempt of 3)..."
            Invoke-WebRequest -Uri $Url -OutFile $PartialArchive -UseBasicParsing
            $ActualSha256 = (Get-FileHash -LiteralPath $PartialArchive -Algorithm SHA256).Hash
            if ($ActualSha256 -ne $ExpectedSha256) {
                throw "Zig archive checksum mismatch. Expected $ExpectedSha256, got $ActualSha256."
            }
            Move-Item -LiteralPath $PartialArchive -Destination $Archive -Force
            $ArchiveReady = $true
            break
        }
        catch {
            Remove-ToolPath $PartialArchive
            if ($Attempt -eq 3) { throw }
            Write-Warning "Zig download failed: $($_.Exception.Message)"
            Start-Sleep -Seconds (2 * $Attempt)
        }
    }
}

$ActualSha256 = (Get-FileHash -LiteralPath $Archive -Algorithm SHA256).Hash
if ($ActualSha256 -ne $ExpectedSha256) {
    throw "Zig archive checksum mismatch. Expected $ExpectedSha256, got $ActualSha256."
}

if (Test-Path -LiteralPath $ZigDirectory) {
    Remove-ToolPath $ZigDirectory
}
Expand-Archive -LiteralPath $Archive -DestinationPath $ToolsRoot
if (-not (Test-Path -LiteralPath $Zig)) {
    throw "Zig extraction did not create $Zig"
}
Write-Output $Zig
