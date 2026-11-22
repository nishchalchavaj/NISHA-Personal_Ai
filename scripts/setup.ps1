param([string]$Python = 'python', [switch]$Desktop, [switch]$Voice)
$ErrorActionPreference = 'Stop'
$project = Split-Path -Parent $PSScriptRoot
Set-Location -LiteralPath $project
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & $Python -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Install Python 3.11 or 3.12, then rerun setup.' }
}
$extras = @('gateway', 'dev')
if ($Desktop) { $extras += 'desktop' }
if ($Voice) { $extras += 'voice' }
$package = '.[{0}]' -f ($extras -join ',')
if (Test-Path -LiteralPath 'requirements.lock') {
    & '.\.venv\Scripts\python.exe' -m pip install -c requirements.lock -e $package
} else {
    & '.\.venv\Scripts\python.exe' -m pip install -e $package
}
if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
$privateData = & '.\.venv\Scripts\python.exe' -c 'from nisha.settings import load_settings; print(load_settings().data_dir)'
if ($LASTEXITCODE -ne 0) { throw 'Could not resolve the configured private data directory.' }
[System.IO.Directory]::CreateDirectory($privateData) | Out-Null
$securityReports = Join-Path $privateData 'reports'
[System.IO.Directory]::CreateDirectory($securityReports) | Out-Null
& (Join-Path $PSScriptRoot 'secure_data.ps1') -DataDir $privateData -BackupFile (Join-Path $securityReports 'security-acl-before.sddl')
& (Join-Path $PSScriptRoot 'secure_data.ps1') -DataDir $project -BackupFile (Join-Path $securityReports 'security-project-acl-before.sddl')
if (-not (Test-Path -LiteralPath '.env')) { Copy-Item -LiteralPath '.env.example' -Destination '.env' }
$envPath = Join-Path $project '.env'
$envText = [System.IO.File]::ReadAllText($envPath)
foreach ($name in @('NISHA_GATEWAY_KEY', 'NISHA_API_KEY')) {
    if ($envText -match ('(?m)^{0}=\s*$' -f $name)) {
        $bytes = New-Object byte[] 32
        $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
        $rng.GetBytes($bytes)
        $rng.Dispose()
        $secret = 'sk-nisha-' + [Convert]::ToBase64String($bytes).Replace('+','-').Replace('/','_').TrimEnd('=')
        $envText = [regex]::Replace($envText, ('(?m)^{0}=\s*$' -f $name), ($name + '=' + $secret))
    }
}
[System.IO.File]::WriteAllText($envPath, $envText)
if ($Voice) {
    & '.\.venv\Scripts\python.exe' scripts\setup_speech.py
    if ($LASTEXITCODE -ne 0) { throw 'Local speech model download failed. Run scripts\setup_speech.py again.' }
}
Write-Output 'Ready. Start the gateway: .\.venv\Scripts\python.exe -m nisha gateway'
Write-Output 'Then chat in a second terminal: .\.venv\Scripts\python.exe -m nisha chat'

