# purpose: turn Windows Error Reporting LocalDumps on, off or report it for ONE exe (default: the game's exe, from its proxy adapter's identity.json): full dumps written out of process, so they work when the game's heap is corrupt and the in-process minidump is empty
# usage: powershell -ExecutionPolicy Bypass -File wer_localdumps.ps1 -Mode status|enable|disable [-ExeName <game exe>] [-DumpFolder <path>] [-DumpCount 5]   (enable/disable need an elevated prompt: "Enable crash dumps.cmd")
# when: once per PC before PC tests (Liam runs "Enable crash dumps.cmd"); after any start-up crash read these dumps FIRST (empire-remastered LEARNINGS lesson 23)
# not-a-verb: runs on Windows as administrator, outside the repo checkout
# Ported from empire-remastered rml_mod/tools/crash_dumps/wer_localdumps.ps1. Only the HKLM ...\LocalDumps\<ExeName> subkey is written,
# in the 64-bit registry view (a 32-bit PowerShell would be redirected to Wow6432Node, which WER does not read). The default dump folder
# is OUTSIDE the game folder (%LOCALAPPDATA%\CrashDumps\<mod_dir>, stored unexpanded), so a dump never breaks the byte-exact
# uninstall and the key keeps working after the mod is removed. The proxy logs the key's state at every start ("crash: WER LocalDumps").
param([ValidateSet('status', 'enable', 'disable')][string]$Mode = 'status', [string]$ExeName = '',
      [string]$DumpFolder = '', [int]$DumpCount = 5)
$ErrorActionPreference = 'Stop'
# defaults from the game (J12: no game name here): the repo above this script (a wsc.toml), its proxy adapter (proxy\tools\layout.py)
if (-not $ExeName -or -not $DumpFolder) {
    $own = $PSScriptRoot; while ($own -and -not (Test-Path -LiteralPath (Join-Path $own 'wsc.toml'))) { $own = Split-Path $own }
    $id = $null
    if ($own) {
        foreach ($py in 'python', 'python3', 'py') {
            if (-not (Get-Command $py -ErrorAction SilentlyContinue)) { continue }
            $ad = & $py (Join-Path $own 'proxy\tools\layout.py') proxy-adapter 2>$null
            if ($LASTEXITCODE -eq 0 -and $ad) { $id = [IO.File]::ReadAllText((Join-Path $ad 'identity.json')) | ConvertFrom-Json; break }
        }
    }
    if (-not $id) { throw 'no -ExeName and no proxy adapter identity.json to take it from (run it from the repo, or pass -ExeName and -DumpFolder)' }
    if (-not $ExeName) { $ExeName = [string]$id.exe_name }
    if (-not $DumpFolder) { $DumpFolder = '%LOCALAPPDATA%\CrashDumps\' + [string]$id.mod_dir }
}
$parentPath = 'SOFTWARE\Microsoft\Windows\Windows Error Reporting\LocalDumps'
$admin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
$hklm = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::LocalMachine, [Microsoft.Win32.RegistryView]::Registry64)
Write-Output ("wer_localdumps {0}: {1}, elevated {2}, key HKLM\{3}\{4}" -f $Mode, [Environment]::UserName, $admin, $parentPath, $ExeName)

$script:statusOk = $false
function Show-Status {   # prints; the result goes to $script:statusOk (a return value would be mixed into the printed lines)
    $script:statusOk = $false
    $k = $hklm.OpenSubKey("$parentPath\$ExeName")
    if (-not $k) { Write-Output "WER LOCALDUMPS: OFF for $ExeName"; return }
    $f = $k.GetValue('DumpFolder', $null, [Microsoft.Win32.RegistryValueOptions]::DoNotExpandEnvironmentNames)
    $t = $k.GetValue('DumpType'); $c = $k.GetValue('DumpCount'); $k.Close()
    $expanded = [Environment]::ExpandEnvironmentVariables($f)
    $n = @(Get-ChildItem -Path $expanded -Filter '*.dmp' -ErrorAction SilentlyContinue).Count
    Write-Output ("WER LOCALDUMPS: ON for {0}  DumpType={1} DumpCount={2} DumpFolder={3} ({4}), dumps there: {5}" -f $ExeName, $t, $c, $f, $expanded, $n)
    $script:statusOk = ($t -eq 2) -and ($f -eq $DumpFolder) -and ($c -eq $DumpCount)
}

try {
    switch ($Mode) {
        'status' { Show-Status; exit 0 }
        'disable' {
            $p = $hklm.OpenSubKey($parentPath, $true)
            if ($p -and ($p.GetSubKeyNames() -contains $ExeName)) { $p.DeleteSubKey($ExeName); Write-Output "removed HKLM\$parentPath\$ExeName" }
            else { Write-Output "nothing to remove (no $ExeName subkey)" }
            if ($p) { $p.Close() }
            Show-Status; exit 0
        }
        'enable' {
            $k = $hklm.CreateSubKey("$parentPath\$ExeName")
            $k.SetValue('DumpFolder', $DumpFolder, [Microsoft.Win32.RegistryValueKind]::ExpandString)
            $k.SetValue('DumpType', 2, [Microsoft.Win32.RegistryValueKind]::DWord)
            $k.SetValue('DumpCount', $DumpCount, [Microsoft.Win32.RegistryValueKind]::DWord)
            $k.Close()
            New-Item -ItemType Directory -Force -Path ([Environment]::ExpandEnvironmentVariables($DumpFolder)) | Out-Null
            Show-Status; if ($script:statusOk) { exit 0 } else { exit 1 }
        }
    }
} catch [System.UnauthorizedAccessException], [System.Security.SecurityException] {
    Write-Output "ACCESS DENIED (elevated: $admin): nothing changed. Double-click 'Enable crash dumps.cmd' (it asks for admin rights)."
    exit 5
}
