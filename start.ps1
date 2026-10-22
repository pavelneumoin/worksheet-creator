$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$projectPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $projectPython)) {
    Write-Host 'Сначала создайте окружение по инструкции RUN.md.'
    exit 1
}
& $projectPython (Join-Path $PSScriptRoot 'run_local.py')
