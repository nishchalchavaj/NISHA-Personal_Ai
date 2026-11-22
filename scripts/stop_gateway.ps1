$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
$pidPath = Join-Path $project 'data\gateway.pid'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Output 'No managed background gateway.'; exit 0 }
$gatewayPid = [int][System.IO.File]::ReadAllText($pidPath)
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $gatewayPid"
if ($process -and $process.CommandLine -like "*$project\.venv*" -and
    $process.CommandLine -match '\-m\s+nisha\s+gateway') {
    function Stop-OwnedChildren([int]$parentId) {
        foreach ($child in Get-CimInstance Win32_Process -Filter "ParentProcessId = $parentId") {
            if ($child.CommandLine -like "*$project\.venv*") {
                Stop-OwnedChildren $child.ProcessId
                Stop-Process -Id $child.ProcessId -ErrorAction SilentlyContinue
            }
        }
    }
    Stop-OwnedChildren $gatewayPid
    Stop-Process -Id $gatewayPid -ErrorAction SilentlyContinue
    Write-Output 'Stopped the NISHA-managed background gateway.'
} else {
    Write-Output 'PID is stale or does not belong to this launcher; no process stopped.'
}
Remove-Item -LiteralPath $pidPath

