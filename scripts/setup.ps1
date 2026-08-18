param(
    [string]$PythonExecutable = ""
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$VirtualPython = Join-Path $ProjectRoot '.venv\Scripts\python.exe'

if (-not (Test-Path -LiteralPath $VirtualPython)) {
    if ($PythonExecutable) {
        $PythonCommand = Get-Command $PythonExecutable -ErrorAction Stop
        & $PythonCommand.Source -m venv (Join-Path $ProjectRoot '.venv')
    }
    elseif (Get-Command py.exe -ErrorAction SilentlyContinue) {
        & py.exe -3.11 -m venv (Join-Path $ProjectRoot '.venv')
    }
    elseif (Get-Command python.exe -ErrorAction SilentlyContinue) {
        & python.exe -m venv (Join-Path $ProjectRoot '.venv')
    }
    else {
        throw 'Python 3.11+ was not found. Install Python or pass -PythonExecutable.'
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& $VirtualPython -m pip install --upgrade pip
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
& $VirtualPython -m pip install -e "${ProjectRoot}[dev]"
exit $LASTEXITCODE
