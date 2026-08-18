$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Virtual environment is missing. Run scripts\setup.ps1 first.'
}
Push-Location $ProjectRoot
try {
    & $Python -m eu4_assistant.app
    $ExitCode = $LASTEXITCODE
}
finally {
    Pop-Location
}
exit $ExitCode
