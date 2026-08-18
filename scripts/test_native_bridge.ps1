$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Python = Join-Path $ProjectRoot '.venv\Scripts\python.exe'
$Zig = (& (Join-Path $PSScriptRoot 'get_zig.ps1') | Select-Object -Last 1)
$BuildRoot = Join-Path $ProjectRoot 'build\native'
$Harness = Join-Path $BuildRoot 'EU4BridgeHarness.exe'
$Ready = Join-Path $BuildRoot 'harness_ready.json'
$Result = Join-Path $BuildRoot 'harness_autosave.json'

if (-not (Test-Path -LiteralPath $Python)) {
    throw 'Virtual environment is missing. Run scripts\setup.ps1 first.'
}

& (Join-Path $PSScriptRoot 'build_native.ps1')
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Zig c++ -target x86_64-windows-gnu -std=c++20 -O2 -municode `
    (Join-Path $ProjectRoot 'native\bridge_harness.cpp') `
    -o $Harness -lshell32 -luser32 -lkernel32
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Remove-Item -LiteralPath $Ready -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $Result -Force -ErrorAction SilentlyContinue
$HarnessProcess = Start-Process -FilePath $Harness `
    -ArgumentList @("`"$Ready`"", "`"$Result`"") -WindowStyle Hidden -PassThru
try {
    $Deadline = [DateTime]::UtcNow.AddSeconds(10)
    while (-not (Test-Path -LiteralPath $Ready)) {
        if ([DateTime]::UtcNow -ge $Deadline) { throw 'Harness did not become ready.' }
        Start-Sleep -Milliseconds 50
    }
    & (Join-Path $BuildRoot 'EU4BridgeInjector.exe') $HarnessProcess.Id `
        (Join-Path $BuildRoot 'EU4AutoSaveBridge.dll')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $Python (Join-Path $ProjectRoot 'tools\exercise_native_bridge.py') $Ready $Result
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    if (-not $HarnessProcess.WaitForExit(5000)) {
        throw 'Harness did not exit after WM_CLOSE.'
    }
} finally {
    if (-not $HarnessProcess.HasExited) {
        Stop-Process -Id $HarnessProcess.Id -Force
    }
}
