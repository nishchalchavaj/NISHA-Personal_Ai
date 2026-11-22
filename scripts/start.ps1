param([switch]$NoDesktop, [switch]$Background)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
$python = Join-Path $project '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $python) -or -not (Test-Path -LiteralPath '.env')) {
    throw 'Run scripts\setup.ps1 -Desktop -Voice first.'
}
if (-not $NoDesktop) {
    $pythonw = Join-Path $project '.venv\Scripts\pythonw.exe'
    # Start listening immediately; the desktop supervises both local services.
    $arguments = @('-m', 'nisha', 'desktop')
    if ($Background) { $arguments += '--background' }
    Start-Process -FilePath $pythonw -ArgumentList $arguments -WorkingDirectory $project -WindowStyle Hidden
} else {
    & $python -m nisha services
    if ($LASTEXITCODE -ne 0) { throw 'Local engine is not ready. Check data\nisha.log and local service logs.' }
}


