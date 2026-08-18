param(
    [switch]$All
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot)).TrimEnd([char]92)
$Targets = @(
    (Join-Path $ProjectRoot 'build'),
    (Join-Path $ProjectRoot 'dist'),
    (Join-Path $ProjectRoot 'logs'),
    (Join-Path $ProjectRoot 'config'),
    (Join-Path $ProjectRoot 'archives'),
    (Join-Path $ProjectRoot 'src\eu4_mp_assistant.egg-info'),
    (Join-Path $ProjectRoot 'data\assistant.sqlite3'),
    (Join-Path $ProjectRoot 'data\assistant.sqlite3-shm'),
    (Join-Path $ProjectRoot 'data\assistant.sqlite3-wal')
)
if ($All) {
    $Targets += (Join-Path $ProjectRoot '.venv')
    $Targets += (Join-Path $ProjectRoot '.tools')
    $Targets += (Join-Path $ProjectRoot 'data\province_index.json')
    $Targets += (Join-Path $ProjectRoot 'data\map_cache')
}

foreach ($Target in $Targets) {
    $Resolved = [IO.Path]::GetFullPath($Target).TrimEnd([char]92)
    if (-not $Resolved.StartsWith($ProjectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe cleanup target: $Resolved"
    }
    if (Test-Path -LiteralPath $Resolved) {
        Remove-Item -LiteralPath $Resolved -Recurse -Force
    }
}

Get-ChildItem -LiteralPath $ProjectRoot -Recurse -Directory -Force |
    Where-Object { $_.Name -in @('__pycache__', '.pytest_cache') } |
    Sort-Object FullName -Descending |
    ForEach-Object {
        if ($_.FullName.StartsWith($ProjectRoot + '\', [StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $_.FullName -Recurse -Force
        }
    }
