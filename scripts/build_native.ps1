param(
    [string]$OutputDirectory = ""
)

$ErrorActionPreference = 'Stop'
$ProjectRoot = [IO.Path]::GetFullPath((Split-Path -Parent $PSScriptRoot))
$Zig = (& (Join-Path $PSScriptRoot 'get_zig.ps1') | Select-Object -Last 1)
$Output = if ($OutputDirectory) {
    [IO.Path]::GetFullPath($OutputDirectory)
} else {
    Join-Path $ProjectRoot 'build\native'
}

New-Item -ItemType Directory -Path $Output -Force | Out-Null

& $Zig c++ -target x86_64-windows-gnu -std=c++20 -O2 -shared `
    (Join-Path $ProjectRoot 'native\bridge.cpp') `
    -o (Join-Path $Output 'EU4AutoSaveBridge.dll') -luser32 -lkernel32
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Zig c++ -target x86_64-windows-gnu -std=c++20 -O2 -municode `
    (Join-Path $ProjectRoot 'native\injector.cpp') `
    -o (Join-Path $Output 'EU4BridgeInjector.exe') -luser32 -lkernel32
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& $Zig c++ -target x86_64-windows-gnu -std=c++20 -O2 -municode `
    (Join-Path $ProjectRoot 'native\launcher.cpp') `
    -o (Join-Path $Output 'EU4AutoSaveLauncher.exe') `
    '-Wl,--subsystem,windows' -lshell32 -luser32 -lkernel32
exit $LASTEXITCODE

