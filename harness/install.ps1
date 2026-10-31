# purpose: install or uninstall the watcher on the PC from a harness kit: sha256-checked copy into the watcher root, a logon scheduled task (Register-ScheduledTask, no admin), first start and a health check
# usage: "Install watcher.cmd" / "Uninstall watcher.cmd" (double-click); or powershell -File install.ps1 -Kit <kit dir> [-Root <dir>] [-Uninstall] [-NoTask] [-NoStart] [-TaskName <name>]
# when: once per PC for the first install (Liam); host tests run it with -NoTask or a test task name; later updates use the watcher's update job, not this
# not-a-verb: runs on the PC under Windows PowerShell 5.1 from the kit folder, outside the repo checkout
param([Parameter(Mandatory = $true)][string]$Kit, [string]$Root = '', [switch]$Uninstall, [switch]$NoTask, [switch]$NoStart, [string]$TaskName = '')
$ErrorActionPreference = 'Stop'
$Utf8 = New-Object Text.UTF8Encoding $false
$Inv = [Globalization.CultureInfo]::InvariantCulture
$Kit = [IO.Path]::GetFullPath($Kit).TrimEnd('\', '/')
function Utc { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd\THH:mm:ss\Z', $Inv) }
function Sha([string]$p) { return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() }
$man = [IO.File]::ReadAllText((Join-Path $Kit 'manifest.json'), $Utf8) | ConvertFrom-Json
if ($man.kind -ne 'harness') { throw "$Kit is not a harness kit (kind=$($man.kind))" }
if (-not $Root) { $Root = [string]$man.watcher_root }
if (-not $TaskName) { $TaskName = [string]$man.task_name }
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
if ($TaskName -eq 'rml_mod watcher') { throw "refusing to touch the earlier remaster's scheduled task 'rml_mod watcher'" }
if (-not (Test-Path -LiteralPath $Root)) { New-Item -ItemType Directory -Path $Root -Force | Out-Null }
$logFile = Join-Path $Root 'install.log'
function Say([string]$m) { $l = "[$(Utc)] $m"; Write-Output $l; try { [IO.File]::AppendAllText($logFile, "$l`r`n", $Utf8) } catch { } }
function AliveAge { try { return ((Get-Date) - (Get-Item -LiteralPath (Join-Path $Root 'watcher.alive')).LastWriteTime).TotalSeconds } catch { return $null } }
function Watcher-Procs {
    $needle = (Join-Path (Join-Path $Root 'src') 'watcher.ps1').ToLower()
    return @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($needle) })
}
function Finish([int]$code, [string]$what) {
    $r = [ordered]@{ action = $(if ($Uninstall) { 'uninstall' } else { 'install' }); ok = ($code -eq 0); message = $what; at_utc = (Utc); kit_id = $man.kit_id; root = $Root; task = $TaskName }
    try { [IO.File]::WriteAllText((Join-Path $Root 'install_result.json'), ($r | ConvertTo-Json), $Utf8) } catch { }
    Say $what
    exit $code
}

if ($Uninstall) {
    $stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd\THHmmss\Z', $Inv)
    if ((AliveAge) -ne $null -and (AliveAge) -lt 10) {
        [IO.File]::WriteAllText((Join-Path $Root 'watcher.stop'), "uninstall`r`n", $Utf8)
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline -and @(Watcher-Procs).Count) { Start-Sleep -Milliseconds 500 }
        foreach ($p in (Watcher-Procs)) { Say "watcher did not stop on watcher.stop - stopping powershell $($p.ProcessId)"; Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
    }
    if (-not $NoTask) { Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false -ErrorAction SilentlyContinue; Say "scheduled task '$TaskName' removed" }
    $src = Join-Path $Root 'src'
    if (Test-Path -LiteralPath $src) {
        $d = Join-Path (Join-Path $Root '_to_delete') "uninstall_$stamp"; New-Item -ItemType Directory -Path $d -Force | Out-Null
        Move-Item -LiteralPath $src -Destination (Join-Path $d 'src')
        Say "src\ moved to _to_delete\uninstall_$stamp (jobs, logs, runs and profiles are kept)"
    }
    Finish 0 "uninstalled: task '$TaskName' removed, files moved to _to_delete; the game folder was not touched"
}

# ---- install ---------------------------------------------------------------------------------------------------------------
# 1. the installer itself must be the file the manifest names (a stale resend of the kit folder is the classic failure)
foreach ($kf in @($man.kit_files)) {
    $p = Join-Path $Kit $kf.name
    if (-not (Test-Path -LiteralPath $p) -or (Sha $p) -ne $kf.sha256) { Finish 2 "kit file $($kf.name) is missing or does not match the manifest sha256 (stale or partial copy): nothing installed. Send the kit again under a new id." }
}
# 2. every staged file, before anything is written
$plan = @()
foreach ($e in @($man.files)) {
    $rel = ([string]$e.path) -replace '/', '\'
    if ($rel -match '(^|\\)\.\.(\\|$)' -or [IO.Path]::IsPathRooted($rel) -or -not ($rel -match '^(src|profiles)\\')) { Finish 2 "kit path '$($e.path)' is outside src\ and profiles\: nothing installed" }
    $s = Join-Path $Kit $e.staged
    if (-not (Test-Path -LiteralPath $s) -or (Sha $s) -ne $e.sha256) { Finish 2 "staged file $($e.staged) is missing or does not match the manifest sha256 (stale or partial copy): nothing installed. Send the kit again under a new id." }
    $plan += [pscustomobject]@{ rel = $rel; staged = $s; sha = [string]$e.sha256 }
}
$age = AliveAge
if ($null -ne $age -and $age -lt 10) { Finish 2 "a watcher is already running for $Root (heartbeat $([int]$age) s old): use the update job instead of the installer" }
foreach ($d in @('jobs', 'runs', 'profiles', 'src', '_to_delete')) { $p = Join-Path $Root $d; if (-not (Test-Path -LiteralPath $p)) { New-Item -ItemType Directory -Path $p -Force | Out-Null } }
foreach ($p in $plan) {
    $dest = Join-Path $Root $p.rel
    $dd = Split-Path $dest; if (-not (Test-Path -LiteralPath $dd)) { New-Item -ItemType Directory -Path $dd -Force | Out-Null }
    $tmp = "$dest.insttmp"
    Copy-Item -LiteralPath $p.staged -Destination $tmp -Force
    if ((Sha $tmp) -ne $p.sha) { Remove-Item -LiteralPath $tmp -Force; Finish 2 "copy of $($p.rel) does not verify" }
    if (Test-Path -LiteralPath $dest) { [IO.File]::Replace($tmp, $dest, [NullString]::Value) } else { [IO.File]::Move($tmp, $dest) }
    if ((Sha $dest) -ne $p.sha) { Finish 2 "$($p.rel) is not what the manifest says after the copy" }
}
Say "$($plan.Count) files installed under $Root (sha256 verified), kit $($man.kit_id), watcher $($man.watcher_version)"
$launcher = Join-Path (Join-Path $Root 'src') 'watch.cmd'
# 3. the logon task: Register-ScheduledTask for the CURRENT user needs no elevation (schtasks /create /sc onlogon is refused for a non-admin)
if (-not $NoTask) {
    $user = "$env:USERDOMAIN\$env:USERNAME"
    $action = New-ScheduledTaskAction -Execute $env:ComSpec -Argument "/c start `"$TaskName`" /min `"$launcher`"" -WorkingDirectory (Split-Path $launcher)
    $trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
    $trigger.Delay = 'PT15S'
    $principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -StartWhenAvailable
    Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Description "$TaskName`: the PC watcher ($launcher)." -Force | Out-Null
    $t = Get-ScheduledTask -TaskName $TaskName
    Say "task: '$TaskName' state=$($t.State) trigger=AtLogOn user=$user action=$($t.Actions[0].Execute) $($t.Actions[0].Arguments)"
}
# 4. first start, detached and hidden, and a health check: the watcher must report itself
if (-not $NoStart) {
    $cl = "$env:ComSpec /c `"`"$launcher`"`""
    $si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cl; CurrentDirectory = (Split-Path $launcher); ProcessStartupInformation = $si }
    Say "started the launcher (pid $($r.ProcessId), rc $($r.ReturnValue))"
    $ok = $null; $deadline = (Get-Date).AddSeconds(40)
    while ((Get-Date) -lt $deadline -and -not $ok) {
        $a = AliveAge
        if ($null -ne $a -and $a -lt 10) { try { $ok = [IO.File]::ReadAllText((Join-Path $Root 'watcher.status'), $Utf8) | ConvertFrom-Json } catch { } }
        Start-Sleep -Milliseconds 500
    }
    if (-not $ok) { Finish 1 'installed, but the watcher did not report itself within 40 s: see watcher.log in the root' }
    Say "watcher $($ok.version) is running (pid $($ok.pid), $($ok.ps_version))"
}
Finish 0 "installed: watcher root $Root, task '$TaskName'$(if ($NoTask) { ' (not registered: -NoTask)' })"
