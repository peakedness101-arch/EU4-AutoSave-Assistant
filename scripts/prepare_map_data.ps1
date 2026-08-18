param(
    [Parameter(Mandatory = $true)]
    [string]$GameDirectory
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$GameRoot = [IO.Path]::GetFullPath($GameDirectory)

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Virtual environment is missing. Run scripts\setup.ps1 first.'
}
if (-not (Test-Path -LiteralPath (Join-Path $GameRoot 'map\provinces.bmp'))) {
    throw "Not an EU4 installation directory: $GameRoot"
}

& $Python (Join-Path $PSScriptRoot 'build_map_cache.py') `
    $GameRoot `
    (Join-Path $ProjectRoot 'data\map_cache') `
    (Join-Path $ProjectRoot 'data\province_index.json')
exit $LASTEXITCODE

