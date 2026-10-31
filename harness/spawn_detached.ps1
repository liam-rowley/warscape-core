# purpose: start a program fully detached from the calling job (WMI Win32_Process.Create), so it inherits none of the job's handles and is not in its process tree
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File spawn_detached.ps1 -Path <x.cmd|x.exe> [-Arguments "<args>"] [-Cwd <dir>] [-Visible]   (from a watcher job; the job must print a line)
# when: any long-lived process a job starts (a probe, a test watcher, the updater); never with cmd's `start` inside a job
# not-a-verb: runs on the PC under Windows PowerShell 5.1, outside the repo checkout
# Hidden by default (ShowWindow=0): otherwise Windows opens an empty console on the desktop for the whole run.
param([Parameter(Mandatory = $true)][string]$Path, [string]$Arguments = '', [string]$Cwd = '', [switch]$Visible)
$ErrorActionPreference = 'Stop'
$full = [IO.Path]::GetFullPath($Path)
if (-not (Test-Path -LiteralPath $full)) { "not found: $full"; exit 2 }
if (-not $Cwd) { $Cwd = Split-Path $full }
if ($full -match '\.(cmd|bat)$') { $cl = "$env:ComSpec /c `"`"$full`" $Arguments`"" } else { $cl = "`"$full`" $Arguments" }
$si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]$(if ($Visible) { 1 } else { 0 }) }
$r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cl; CurrentDirectory = $Cwd; ProcessStartupInformation = $si }
"spawned pid=$($r.ProcessId) rc=$($r.ReturnValue): $cl (cwd $Cwd)"
exit [int]$r.ReturnValue
