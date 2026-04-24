Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonExe = Join-Path $repoRoot '.venv-cpython\Scripts\python.exe'
$specFile = Join-Path $repoRoot 'simulation.spec'

if (-not (Test-Path $pythonExe)) {
    throw "Missing build interpreter: $pythonExe"
}

Push-Location $repoRoot
try {
    & $pythonExe -m PyInstaller --noconfirm --clean $specFile
}
finally {
    Pop-Location
}
