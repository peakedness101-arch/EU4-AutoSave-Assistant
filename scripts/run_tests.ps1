$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Virtual environment is missing. Run scripts\setup.ps1 first.'
}
$env:QT_QPA_PLATFORM = 'offscreen'
Push-Location $ProjectRoot
try {
    & $Python -m pytest
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $ExitCode
