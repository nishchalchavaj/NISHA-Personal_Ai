param(
    [Parameter(Mandatory = $true)][string]$DataDir,
    [string]$BackupFile
)
$ErrorActionPreference = 'Stop'
if ($DataDir.StartsWith('\\') -or $DataDir.StartsWith('//')) { throw 'Choose local NTFS storage, not a network share.' }
Import-Module -Name (Join-Path $PSHOME 'Modules\Microsoft.PowerShell.Security\Microsoft.PowerShell.Security.psd1') -Force
$target = [System.IO.Path]::GetFullPath($DataDir).TrimEnd('\')
if (-not (Test-Path -LiteralPath $target -PathType Container) -or
    $target -eq [System.IO.Path]::GetPathRoot($target).TrimEnd('\')) {
    throw 'Choose an existing NISHA data directory, not a drive root.'
}
# Refuse junctions/symlinks before changing an inheritable ACL.
$queue = [System.Collections.Generic.Queue[string]]::new()
$queue.Enqueue($target)
while ($queue.Count -gt 0) {
    $directory = $queue.Dequeue()
    foreach ($item in @(Get-Item -LiteralPath $directory -Force) + @(Get-ChildItem -LiteralPath $directory -Force)) {
        if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
            throw 'Data contains a reparse point. Resolve linked storage before securing it.'
        }
        if ($item.PSIsContainer -and $item.FullName -ne $directory) { $queue.Enqueue($item.FullName) }
    }
}
$acl = Get-Acl -LiteralPath $target
if ($BackupFile -and -not (Test-Path -LiteralPath $BackupFile)) {
    $acl.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access) |
        Set-Content -LiteralPath $BackupFile -Encoding UTF8
}
$broad = @('S-1-1-0', 'S-1-5-11', 'S-1-5-32-545')
$inherited = @($acl.Access | Where-Object { $_.IsInherited })
$acl.SetAccessRuleProtection($true, $false)
foreach ($rule in $inherited) {
    $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    if ($sid -in $broad -and $rule.AccessControlType -eq 'Allow') { continue }
    $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        $rule.IdentityReference, $rule.FileSystemRights, $rule.InheritanceFlags,
        $rule.PropagationFlags, $rule.AccessControlType
    ))
}
foreach ($rule in @($acl.Access)) {
    $sid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value
    if ($sid -in $broad -and $rule.AccessControlType -eq 'Allow') { $acl.RemoveAccessRuleAll($rule) }
}
$identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
foreach ($sid in @($identity, [System.Security.Principal.SecurityIdentifier]::new('S-1-5-18'))) {
    $acl.AddAccessRule([System.Security.AccessControl.FileSystemAccessRule]::new(
        $sid, 'FullControl', 'ContainerInherit, ObjectInherit', 'None', 'Allow'
    ))
}
$python = Join-Path (Split-Path -Parent $PSScriptRoot) '.venv\Scripts\python.exe'
$applyDacl = @'
import sys
import win32security
descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(sys.argv[2], 1)
win32security.SetNamedSecurityInfo(sys.argv[1], win32security.SE_FILE_OBJECT,
    win32security.DACL_SECURITY_INFORMATION | win32security.PROTECTED_DACL_SECURITY_INFORMATION,
    None, None, descriptor.GetSecurityDescriptorDacl(), None)
'@
# Update only the DACL, never the owner or audit policy. Set-Acl on a directory
# owned by a previous setup account can otherwise request SeSecurityPrivilege.
& $python -c $applyDacl $target ($acl.GetSecurityDescriptorSddlForm([System.Security.AccessControl.AccessControlSections]::Access))
if ($LASTEXITCODE -ne 0) { throw 'Could not apply the private data access rules.' }
$remaining = @((Get-Acl -LiteralPath $target).Access | Where-Object {
    $_.AccessControlType -eq 'Allow' -and $_.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier]).Value -in $broad
})
if ($remaining.Count -ne 0) { throw 'Broad access remains on the data directory.' }
@{ status = 'secured'; broad_access = $false; path = $target } | ConvertTo-Json -Compress
