# purpose: integration host tests for the harness on Windows: a real watcher (through watch.cmd) with fake games, driven by job files; refusals, lock, launch/kill, zombie, profiles, auto-restore, hang dump and archive, timeouts, queue rules, update with rollback, installer and uninstaller
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File Test-Integration.ps1 [-Repo <repo root>] [-Only <case-name regex>] [-Repeat <n>]   (CI: GitHub's Windows runner, Windows PowerShell 5.1; needs python for the real-kit test)
# when: on every push (CI job harness-windows); never on the PC, it starts and kills processes named Fake*.exe and sets the time zone of the machine while it runs
# not-a-verb: a PowerShell test script, not a repo operation
# -Only/-Repeat chase a flaky case (J19): the watcher starts once, each selected case runs n times in a row (auto-restore and
# the update rollbacks are repeat-safe since J42: they read the log after their own mark). Cases that build on an
# earlier case's state (the update rollbacks need 'update: a good kit') only pass when that case is selected too.
param([string]$Repo = '', [string]$Only = '', [ValidateRange(1, 1000)][int]$Repeat = 1)
# the whole suite is not repeat-safe (see above): a repeat of every case fails cases that are fine, so it is refused before anything starts
if ($Repeat -gt 1 -and -not $Only) { Write-Host 'FAILED: -Repeat needs -Only (the whole integration suite is not repeat-safe)'; exit 2 }
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Test-Lib.ps1')
$script:TcOnly = $Only; $script:TcRepeat = $Repeat   # Tc names: a $script:Only in Test-Lib would BE the -Only param (case-insensitive, same scope) and reset it (J19 run 40898907246)
if (-not $Repo) { $Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
# the harness scripts: harness\core\ before the move to warscape-core, harness\ after it (J12); the tests find them, not a layout
$core = Split-Path $PSScriptRoot; if (Test-Path -LiteralPath (Join-Path $core 'core\watcher.ps1')) { $core = Join-Path $core 'core' }
$Inv = [Globalization.CultureInfo]::InvariantCulture
$tmp = New-Tmp 'int'
$state = Join-Path $tmp 'state'; $root = Join-Path $state 'watcher'; $kits = Join-Path $state 'kits'
$game = Join-Path $tmp 'game'; $app = Join-Path $tmp 'appdata'
New-Item -ItemType Directory -Path (Join-Path $root 'src'), $kits -Force | Out-Null
$SuiteState = @{ n = 0; tz = $null }
$env:WSP_VIRTUALSTORE_ROOT = Join-Path $tmp 'VirtualStore'   # the watcher's VirtualStore guard (fix 1g) looks here, not in the runner's profile

# ---- fake games (compiled here): FakeGame.exe is 32-bit like the real game (the dump path must cope with WoW64) -----------------
$fakeSrc = @'
using System;
using System.Diagnostics;
using System.IO;
using System.Threading;
public static class FAKECLASS {
    public static int Main(string[] a) {
        string mode = a.Length > 0 ? a[0] : "idle";
        string log = a.Length > 1 ? a[1] : null;
        DateTime end = DateTime.UtcNow.AddMinutes(15);
        while (DateTime.UtcNow < end) {
            if (mode == "spin") { Stopwatch sw = Stopwatch.StartNew(); while (sw.ElapsedMilliseconds < 150) { } Thread.Sleep(50); }
            else {
                if (mode == "log" && log != null) { try { File.AppendAllText(log, DateTime.UtcNow.ToString("o") + " tick\r\n"); } catch { } }
                Thread.Sleep(500);
            }
        }
        return 0;
    }
}
'@
function New-Fake([string]$exe, [string]$cls, [string]$platform) {
    $prov = New-Object Microsoft.CSharp.CSharpCodeProvider
    $cp = New-Object System.CodeDom.Compiler.CompilerParameters
    $cp.ReferencedAssemblies.Add("System.dll") | Out-Null; $cp.GenerateExecutable = $true; $cp.OutputAssembly = $exe; $cp.CompilerOptions = "/platform:$platform"
    $res = $prov.CompileAssemblyFromSource($cp, $fakeSrc.Replace('FAKECLASS', $cls))
    if ($res.Errors.HasErrors) { throw ("fake game compile failed: " + (($res.Errors | ForEach-Object { $_.ToString() }) -join '; ')) }
}
New-Item -ItemType Directory -Path $game -Force | Out-Null
New-Fake (Join-Path $game 'FakeGame.exe') 'FakeA' 'x86'
New-Fake (Join-Path $game 'FakeOther.exe') 'FakeB' 'x86'
New-Fake (Join-Path $tmp 'Fake64.exe') 'FakeC' 'x64'
$logPath = Join-Path $game 'logs\proxy.log'
$adapterPath = New-TestAdapter $tmp 'FakeGame.exe' 'FakeOther.exe' ("log `"$logPath`"")
# the exe identity the watcher checks before every launch (J18): a fixture with the fake game's sha1, beside the adapter it is started with
$identityPath = Join-Path $tmp 'exe_identity.json'
$fakeSha1 = (Get-FileHash -LiteralPath (Join-Path $game 'FakeGame.exe') -Algorithm SHA1).Hash.ToLower()
[IO.File]::WriteAllText($identityPath, "{`"sha1`": `"$fakeSha1`"}", $Utf8NoBom)
foreach ($f in 'watcher.ps1', 'watch.cmd', 'update.ps1', 'dump.ps1', 'procfreeze.ps1', 'spawn_detached.ps1', 'vdisplay_probe.ps1', 'win_probe.ps1') { Copy-Item -LiteralPath (Join-Path $core $f) -Destination (Join-Path $root 'src') }
Copy-Item -LiteralPath $adapterPath -Destination (Join-Path $root 'src\adapter.json')
New-Item -ItemType Directory -Path (Join-Path $root 'profiles') -Force | Out-Null
Copy-Item -Path (Join-Path $PSScriptRoot 'fixtures\profiles\*') -Destination (Join-Path $root 'profiles') -Recurse -Force
# The CI runner has no virtual display (the real tool exits 3 there), so the watcher is pointed at a stateful stand-in (test_vdisplay_script).
$vdFake = Join-Path $tmp 'fake_vdisplay.ps1'
[IO.File]::WriteAllText($vdFake, @'
param([switch]$Check, [string]$Size = '', [string]$Set = '', [string]$SaveTo = '', [string]$Restore = '', [string]$Name = '')
$dir = Split-Path $MyInvocation.MyCommand.Path
function Log([string]$m) { [IO.File]::AppendAllText((Join-Path $dir 'vd_calls.txt'), $m + "`r`n") }
$st = ([IO.File]::ReadAllText((Join-Path $dir 'vd_state.txt'))).Trim()
$offered = ([IO.File]::ReadAllText((Join-Path $dir 'vd_offered.txt'))).Trim().Split(',')
function Rect([string]$s) { $p = $s -split 'x'; return ('3839,2160,{0},{1}' -f (3839 + [int]$p[0]), (2160 + [int]$p[1])) }
Log ("call: Check=$Check Size=$Size Set=$Set SaveTo=$SaveTo Restore=$Restore Name=$Name")
if ($st -eq 'none') { Write-Output 'VIRTUAL MISSING: no attached display matches (fake). Nothing was changed.'; exit 3 }
if ($Check) {
    if ($st -eq $Size) { Write-Output "VIRTUAL OK: \\.\DISPLAY10 $st@60Hz rect=$(Rect $st) adapter='Virtual Display Driver'"; exit 0 }
    Write-Output "VIRTUAL WRONG SIZE: \\.\DISPLAY10 is $st but $Size is wanted (fake)"; exit 4
}
if ($Set) {
    if ($offered -notcontains $Set) { Write-Output "MODE NOT OFFERED: $Set is refused by the driver (fake); nothing was changed."; exit 6 }
    if (Test-Path -LiteralPath $SaveTo) { Write-Output 'REFUSED: -SaveTo exists'; exit 7 }
    $p = $st -split 'x'
    [IO.File]::WriteAllText($SaveTo, ('{"name":"' + $Name + '","w":' + $p[0] + ',"h":' + $p[1] + ',"hz":60,"x":3839,"y":2160}'))
    [IO.File]::WriteAllText((Join-Path $dir 'vd_state.txt'), $Set)
    Write-Output "VIRTUAL SET: now $Set (was $st)"; exit 0
}
if ($Restore) {
    $j = [IO.File]::ReadAllText($Restore) | ConvertFrom-Json
    [IO.File]::WriteAllText((Join-Path $dir 'vd_state.txt'), "$($j.w)x$($j.h)")
    Write-Output "VIRTUAL RESTORED: back at $($j.w)x$($j.h)"; exit 0
}
exit 2
'@, [Text.Encoding]::ASCII)
$ini = @"
test_vdisplay_script=$vdFake
hang_s=600
hang_startup_s=2
hung_window_s=5
zombie_wait_s=4
loop_ms=300
job_timeout_s=120
launch_confirm_s=10
dump_wait_s=90
test_hooks=1
"@
[IO.File]::WriteAllText((Join-Path $root 'watcher.ini'), $ini, $Utf8NoBom)

# ---- helpers ------------------------------------------------------------------------------------------------------------------------
function ReadText([string]$p) {
    $fs = New-Object IO.FileStream($p, [IO.FileMode]::Open, [IO.FileAccess]::Read, ([IO.FileShare]'ReadWrite,Delete'))
    try { $sr = New-Object IO.StreamReader($fs, $Utf8NoBom); return $sr.ReadToEnd() } finally { $fs.Dispose() }
}
function Get-St { for ($i = 0; $i -lt 10; $i++) { try { $t = ReadText (Join-Path $root 'watcher.status'); if ($t) { return ($t | ConvertFrom-Json) } } catch { }; Start-Sleep -Milliseconds 120 }; return $null }
function Get-Log { try { return (ReadText (Join-Path $root 'watcher.log')) } catch { return '' } }
# Log-Mark + -Since: match only lines written after the mark, so a repeated case (-Repeat) never matches its previous run's line
function Log-Mark { return (Get-Log).Length }
function Get-LogSince([int]$mark) { $t = Get-Log; if ($t.Length -ge $mark) { return $t.Substring($mark) } else { return $t } }   # shorter: rotated at 2 MB
function Wait-LogMatch([string]$rx, [int]$secs, [string]$what, [int]$Since = 0) { Wait-Until { (Get-LogSince $Since) -match $rx } $secs $what | Out-Null }
function Alive-Age { try { return ((Get-Date) - (Get-Item -LiteralPath (Join-Path $root 'watcher.alive')).LastWriteTime).TotalSeconds } catch { return 9999 } }
function Alive-AgeOf([string]$r) { try { return ((Get-Date) - (Get-Item -LiteralPath (Join-Path $r 'watcher.alive')).LastWriteTime).TotalSeconds } catch { return 9999 } }
function Wait-Watcher([int]$secs = 40) { Wait-Until { (Alive-Age) -lt 4 -and (Get-St) } $secs 'a fresh watcher heartbeat' | Out-Null; return (Get-St) }
# what a failed wait needs to be explained from the CI log alone: the watcher's own log, its heartbeat age and the processes (J42)
function Show-WatcherState([int]$lines = 40) {
    Write-Host "  watcher.alive age: $([int](Alive-Age)) s; watcher.pid: $(try { [IO.File]::ReadAllText((Join-Path $root 'watcher.pid')) } catch { 'none' })"
    if ($SuiteState.launcher) { Write-Host "  launcher exited: $($SuiteState.launcher.HasExited)$(if ($SuiteState.launcher.HasExited) { " (exit $($SuiteState.launcher.ExitCode))" })" }
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($tmp) } | ForEach-Object { Write-Host "  process $($_.ProcessId) $($_.Name) started $($_.CreationDate.ToUniversalTime().ToString('HH:mm:ss'))Z" }
    Write-Host "  watcher.log, last $lines lines:"
    @((Get-Log) -split "`r?`n" | Where-Object { $_ }) | Select-Object -Last $lines | ForEach-Object { Write-Host "    $_" }
}
$script:TcOnFail = { Show-WatcherState }
function Start-TestWatcher {
    $cmd = Join-Path $root 'src\watch.cmd'
    $a = "/d /s /c `"`"$cmd`" -Root `"$root`" -Adapter `"$adapterPath`"`""
    $mark = Log-Mark
    $p = Start-Process -FilePath $env:ComSpec -ArgumentList $a -WindowStyle Hidden -PassThru
    $SuiteState.launcher = $p
    # a new watcher process on a fresh runner reaches its main loop 17 to 35 s after it starts (J42 runs on 66d0fd9 and 97358f5;
    # 39.9 s in run 40970029940), nearly all of it powershell.exe start-up before the first statement (a warm load of the script takes
    # under 3 s), so the start has its own budget; the 40 s heartbeat budget starts once the watcher is in its loop
    try {
        Wait-LogMatch 'watcher [0-9.a-z-]+ started \(pid' 150 'the watcher to reach its main loop (a cold powershell start is slow before its first statement)' -Since $mark
        $up = [regex]::Match((Get-LogSince $mark), 'up (\d+) ms after its process started').Groups[1].Value
        Write-Host "  watcher up after $up ms"
        return (Wait-Watcher 40)
    } catch { Write-Host "FAILED: watcher start: $($_.Exception.Message)"; Show-WatcherState; throw }
}
function Stop-TestWatcher {
    [IO.File]::WriteAllText((Join-Path $root 'watcher.stop'), 'stop', $Utf8NoBom)
    $deadline = (Get-Date).AddSeconds(20)
    while ((Get-Date) -lt $deadline -and (Alive-Age) -lt 4) { Start-Sleep -Milliseconds 300 }
    Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($tmp) -and ($_.Name -in 'powershell.exe', 'cmd.exe') -and $_.ProcessId -ne $PID } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}
function New-JobId([string]$tag) { $SuiteState.n++; return ('t-{0}-{1}-{2}' -f $tag, (Get-Date).ToUniversalTime().ToString('HHmmss'), $SuiteState.n) }
function Submit([string]$body, [string]$id) {
    $j = Join-Path $root 'jobs'
    [IO.File]::WriteAllText((Join-Path $j "$id.tmp"), $body, $Utf8NoBom)
    Move-Item -LiteralPath (Join-Path $j "$id.tmp") -Destination (Join-Path $j "$id.request")
    return $id
}
function Get-Result([string]$id, [int]$secs = 60) {
    $done = Join-Path $root "jobs\$id.done"
    Wait-Until { Test-Path -LiteralPath $done } $secs "result of job $id" | Out-Null
    Start-Sleep -Milliseconds 150
    $d = (ReadText $done) | ConvertFrom-Json
    $o = ''; $op = Join-Path $root "jobs\$id.out"; if (Test-Path -LiteralPath $op) { $o = ReadText $op }
    return @{ d = $d; out = $o; id = $id }
}
function Run-Job([string]$body, [string]$tag = 'j', [int]$secs = 60) { return (Get-Result (Submit $body (New-JobId $tag)) $secs) }
function Set-Lock([string]$owner, [string]$extra = '') {
    [IO.File]::WriteAllText((Join-Path $root 'game.lock'), ("owner=$owner session=ci purpose=host test started=$(UtcNow-Str)$extra`r`n"), $Utf8NoBom)
}
function UtcNow-Str { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd\THH:mm:ss\Z', $Inv) }
function Clear-Lock {
    $l = Join-Path $root 'game.lock'
    if (Test-Path -LiteralPath $l) { $d = Join-Path $root '_to_delete'; New-Item -ItemType Directory -Path $d -Force | Out-Null; $SuiteState.n++; Move-Item -LiteralPath $l -Destination (Join-Path $d "game.lock.test$($SuiteState.n)") -Force }
}
function Stop-Fakes { foreach ($n in 'FakeGame', 'FakeOther', 'Fake64') { Get-Process -Name $n -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue } }
function Fake-Procs([string]$n = 'FakeGame') { return @(Get-Process -Name $n -ErrorAction SilentlyContinue) }
$prefs = Join-Path $app 'scripts\preferences.script.txt'; $keys = Join-Path $app 'custom_keys.keys.xml'
$modIni = Join-Path $game 'testmod.ini'; $dxc = Join-Path $game 'dxvk.conf'
$bprefs = Join-Path $app 'battle_preferences\.sp_default.battle_preferences'   # HIDDEN on the PC (J3 run 20261029_4kcrash: Get-Item without -Force threw)
# one read per file, never Test-Path then hash: the watcher deletes a file between the two while it restores (J42, run 40898971722:
# "Cannot find path ...dxvk.conf"); a file mid-write reads 'busy', which matches no baseline, so a wait simply polls again
function Hash-OrAbsent([string]$p) {
    try { return (Sha256File $p) }
    catch { if ($_.Exception -is [Management.Automation.ItemNotFoundException] -or -not [IO.File]::Exists($p)) { return 'absent' }; return 'busy' }
}
function Hashes { return ((@($prefs, $keys, $bprefs, $modIni, $dxc) | ForEach-Object { Hash-OrAbsent $_ }) -join ',') }
function Pid-Of-Watcher { return [int](Get-St).pid }

try {
    # the machine's time zone is moved far from UTC while the watcher runs: any local-time-with-a-Z-suffix bug shows as a 9 h error
    $SuiteState.tz = (& tzutil.exe /g).Trim()
    & tzutil.exe /s 'Tokyo Standard Time'
    [IO.File]::WriteAllBytes($prefs, [byte[]](0, 255, 13, 10, 10, 13, 0xC3, 0xA9, 200, 1, 2, 3))
    [IO.File]::WriteAllText($keys, '<keys/>', $Utf8NoBom)
    New-Item -ItemType Directory -Path (Split-Path $bprefs) -Force | Out-Null
    [IO.File]::WriteAllBytes($bprefs, [byte[]](1, 2, 3, 4)); (Get-Item -LiteralPath $bprefs -Force).Attributes = 'Hidden'
    $baseline = Hashes
    $st0 = Start-TestWatcher

    Test-Case 'noop and status: results are UTC (machine zone is Tokyo), no BOM, no UTF-16' {
        $r = Run-Job 'noop' 'noop'
        Assert-Eq $r.d.status 'ok' 'noop status'; Assert-Eq $r.d.exit 0 'noop exit'
        Assert-Match $r.d.start_utc '^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ$' 'start_utc format'
        $t = [DateTime]::Parse($r.d.start_utc, $Inv, [Globalization.DateTimeStyles]::AdjustToUniversal)
        Assert-True ([Math]::Abs(($t - [DateTime]::UtcNow).TotalSeconds) -lt 60) "start_utc $($r.d.start_utc) is within a minute of real UTC"
        $s = Run-Job 'status' 'status'
        $j = $s.out | ConvertFrom-Json
        Assert-True ($j.processes -is [array] -or $null -eq $j.processes -or $j.processes.Count -ge 0) 'processes listed'
        Assert-Match $j.heartbeat_utc 'Z$' 'heartbeat is UTC'
        $tz = Run-Job "#ps1`r`nWrite-Output ([TimeZoneInfo]::Local.Id)" 'tz'
        Assert-Match $tz.out 'Tokyo' 'the test really ran under a non-UTC zone'
        foreach ($f in 'watcher.status', 'watcher.log', "jobs\$($r.id).done", "jobs\$($s.id).out") {
            $b = [IO.File]::ReadAllBytes((Join-Path $root $f))
            Assert-True ($b.Length -gt 2) "$f not empty"
            Assert-True (-not ($b[0] -eq 0xEF -and $b[1] -eq 0xBB)) "$f has a UTF-8 BOM"
            Assert-True (-not (($b[0] -eq 0xFF -and $b[1] -eq 0xFE) -or ($b[0] -eq 0xFE -and $b[1] -eq 0xFF))) "$f is UTF-16"
            Assert-True (-not ($b -contains 0)) "$f contains NUL bytes (UTF-16?)"
        }
        $first = (Get-Log) -split "`r?`n" | Select-Object -First 1
        Assert-Match $first '^\[\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\] ' 'log timestamps are UTC with a Z'
    }
    Test-Case 'queue: a job with no output finishes normally and the next job still runs (the earlier remaster watcher 5.0 wedged here)' {
        $a = Submit "@echo off`r`nrem prints nothing" (New-JobId 'empty'); Start-Sleep -Milliseconds 80
        $b = Submit "@echo off`r`nexit /b 3" (New-JobId 'fail'); Start-Sleep -Milliseconds 80
        $c = Submit "@echo off`r`necho line one`r`necho line two" (New-JobId 'normal'); Start-Sleep -Milliseconds 80
        $d = Submit "#ps1`r`n`$x = 1" (New-JobId 'ps1empty'); Start-Sleep -Milliseconds 80
        $e = Submit "#ps1`r`nWrite-Output (`"ps `" + `$PSVersionTable.PSVersion.Major)" (New-JobId 'ps1')
        $f = Submit "#ps1`r`ncmd /c exit 5" (New-JobId 'ps1fail'); Start-Sleep -Milliseconds 80
        $g = Submit "#ps1`r`ncmd /c exit 5`r`nexit 0" (New-JobId 'ps1exit0')
        $ra = Get-Result $a; $rb = Get-Result $b; $rc = Get-Result $c; $rd = Get-Result $d; $re = Get-Result $e; $rf = Get-Result $f; $rg = Get-Result $g
        Assert-Eq $rf.d.status 'failed' 'a ps1 job whose last call failed fails (J13 question 1)'; Assert-Eq $rf.d.exit 5 'with that exit code'
        Assert-Eq $rg.d.status 'ok' 'an explicit exit 0 in the body still wins'
        Assert-Eq $ra.d.status 'ok' 'empty status'; Assert-Eq $ra.d.exit 0 'empty exit'; Assert-Eq $ra.out.Length 0 'empty output stays empty'
        Assert-Eq $rb.d.status 'failed' 'fail status'; Assert-Eq $rb.d.exit 3 'real exit code'
        Assert-Match $rc.out 'line two' 'normal output'
        Assert-Eq $rd.d.status 'ok' 'ps1 empty'; Assert-Match $re.out 'ps 5' 'jobs run under Windows PowerShell 5.1'
        $ts = @($ra, $rb, $rc, $rd, $re) | ForEach-Object { [DateTime]::Parse($_.d.start_utc, $Inv, [Globalization.DateTimeStyles]::AdjustToUniversal) }
        for ($i = 1; $i -lt $ts.Count; $i++) { Assert-True ($ts[$i] -ge $ts[$i - 1]) 'FIFO order' }
    }
    Test-Case 'single instance: a second watcher on the same root exits with 10' {
        $p = Start-Process -FilePath powershell.exe -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $root 'src\watcher.ps1')`" -Root `"$root`" -Adapter `"$adapterPath`"" -WindowStyle Hidden -Wait -PassThru
        Assert-Eq $p.ExitCode 10 'exit code of the second instance'
    }
    Test-Case 'one job error never wedges the slot: output-collection failure and a start failure both finish, the queue moves on' {
        $id = New-JobId 'collect'; New-Item -ItemType Directory -Path (Join-Path $root "jobs\$id.out.wtmp") -Force | Out-Null
        $r = Get-Result (Submit "@echo off`r`necho collect_throws" $id)
        Assert-Eq $r.d.status 'ok' 'status kept'; Assert-Match $r.out 'output could not be collected' 'the failure is noted in the output'
        $r2 = Run-Job "#job test=throw_on_start`r`n@echo off`r`necho hi" 'throw'
        Assert-Eq $r2.d.status 'failed' 'start failure closes as failed'; Assert-Match $r2.d.reason 'watcher error while starting' 'reason'
        $r3 = Run-Job 'noop' 'after'; Assert-Eq $r3.d.status 'ok' 'the queue moved on'
    }
    Test-Case 'job ids are never reused: the second request is refused; the old result stays until the new request is picked up' {
        $first = Run-Job 'noop' 'reuse'
        $long = Submit "@echo off`r`nping -n 7 127.0.0.1 >nul`r`necho long" (New-JobId 'long'); Start-Sleep -Milliseconds 200
        Submit 'noop' $first.id | Out-Null
        Start-Sleep -Milliseconds 800
        $doneNow = ReadText (Join-Path $root "jobs\$($first.id).done")
        Assert-Match $doneNow '"status":\s*"ok"' 'the old result is still there while the new request waits in the queue'
        Get-Result $long | Out-Null
        Wait-Until { (ReadText (Join-Path $root "jobs\$($first.id).done")) -match 'refused' } 30 'the reuse to be refused' | Out-Null
        $r = Get-Result $first.id 40
        Assert-Eq $r.d.status 'refused' 'reused id'; Assert-Match $r.d.reason 'already used' 'reason'
    }
    Test-Case 'job timeout kills the job tree but spares the game; a game started by the job does not block the next job' {
        Set-Lock 'ci1'
        $body = "#job owner=ci1 timeout=5`r`n@echo off`r`nstart `"`" /b `"$game\FakeGame.exe`" idle`r`nping -n 60 127.0.0.1 >nul"
        $r = Run-Job $body 'timeout' 40
        Assert-Eq $r.d.status 'timeout' 'status'; Assert-Eq $r.d.exit -1 'exit'
        Assert-True ((Fake-Procs).Count -eq 1) 'the game the job started is still running'
        $n = Run-Job "@echo off`r`necho after the timeout" 'after' 20
        Assert-Match $n.out 'after the timeout' 'the next job ran (the game holds the first job output handle, but only the .part)'
        $k = Run-Job 'kill owner=ci1' 'kill' 40
        Assert-Eq $k.d.status 'ok' 'kill'; Wait-Until { (Fake-Procs).Count -eq 0 } 10 'game gone' | Out-Null
        Clear-Lock
    }
    Test-Case 'refusals: no lock, wrong owner, scripts that start/kill the game or write its config without an owner' {
        Clear-Lock
        $r = Run-Job 'launch owner=ci1' 'nolock'
        Assert-Eq $r.d.status 'refused' 'no lock'; Assert-Eq $r.d.exit -2 'refused exit'; Assert-Match $r.d.reason 'no game.lock' 'reason names the lock'
        Assert-Eq (Run-Job 'kill owner=ci1' 'nolock2').d.status 'refused' 'kill without a lock'
        Assert-Eq (Run-Job 'profile vanilla owner=ci1' 'nolock3').d.status 'refused' 'profile without a lock'
        Set-Lock 'ci1'
        $w = Run-Job 'launch owner=someone-else' 'wrong'
        Assert-Eq $w.d.status 'refused' 'wrong owner'; Assert-Match $w.d.reason 'does not hold the game' 'reason'
        Assert-Eq (Run-Job 'launch' 'noowner').d.status 'refused' 'no owner in the request'
        $s = Run-Job "@echo off`r`ntaskkill /f /im FakeGame.exe" 'script'
        Assert-Eq $s.d.status 'refused' 'taskkill script without owner'; Assert-Match $s.d.reason 'needs' 'reason'
        $c = Run-Job "@echo off`r`ncopy NUL `"$dxc`"" 'cfg'
        Assert-Eq $c.d.status 'refused' 'config-writing script without owner'
        Assert-True (-not (Test-Path -LiteralPath $dxc)) 'and it did not run'
        $ro = Run-Job "@echo off`r`ntasklist /fi `"imagename eq FakeGame.exe`" /fo csv /nh" 'readonly'
        Assert-Eq $ro.d.status 'ok' 'read-only tasklist is never blocked'
        Clear-Lock
    }
    Test-Case 'exe check (J18): a fake game whose sha1 is not the identity is refused (-2), exe_check=warn launches it with a warning, watcher.status has the verdict' {
        Set-Lock 'ci18'
        [IO.File]::WriteAllText($identityPath, '{"sha1": "0000000000000000000000000000000000000000"}', $Utf8NoBom)
        try {
            $r = Run-Job 'launch visible=1 owner=ci18' 'exebad' 40
            Assert-Eq $r.d.status 'refused' "mismatch refused ($($r.out))"; Assert-Eq $r.d.exit '-2' 'exit -2'
            Assert-Match $r.d.reason 'EXE CHECK: MISMATCH' 'reason'
            Assert-True ((Fake-Procs).Count -eq 0) 'nothing started'
            Wait-Until { $x = Get-St; $x -and $x.exe -and $x.exe.ok -eq $false } 10 'watcher.status exe.ok false' | Out-Null
            $mark = Log-Mark
            [IO.File]::AppendAllText((Join-Path $root 'watcher.ini'), "`r`nexe_check=warn`r`n", $Utf8NoBom)
            Wait-LogMatch 'watcher.ini reloaded' 20 'the settings reload' $mark
            $w = Run-Job 'launch visible=1 owner=ci18' 'exewarn' 40
            Assert-Eq $w.d.status 'ok' "warn launches ($($w.out))"; Assert-Match $w.out 'WARNING \(watcher\): exe check failed' 'with a warning'
            Assert-Eq (Run-Job 'kill owner=ci18' 'exekill' 40).d.status 'ok' 'kill'
        } finally {
            $ini = [IO.File]::ReadAllText((Join-Path $root 'watcher.ini')) -replace "`r`nexe_check=warn`r`n", ''
            [IO.File]::WriteAllText((Join-Path $root 'watcher.ini'), $ini, $Utf8NoBom)
            [IO.File]::WriteAllText($identityPath, "{`"sha1`": `"$fakeSha1`"}", $Utf8NoBom)
            Stop-Fakes; Clear-Lock
        }
        $st = Run-Job 'status' 'exestatus' 20
        Assert-Match $st.out '"ok":\s+true' 'a status job runs the check and shows the verdict'
    }
    Test-Case 'a script that runs git is refused even with the lock held (J18)' {
        Set-Lock 'ci18'
        $g = Run-Job "#job owner=ci18`r`n@echo off`r`ngit --version" 'git' 20
        Assert-Eq $g.d.status 'refused' "git refused ($($g.out))"; Assert-Match $g.d.reason 'runs git' 'reason'
        Clear-Lock
    }
    Test-Case 'launch and kill: pid confirmed, second launch refused, the other title blocks, a foreign lock blocks, kill is clean' {
        Set-Lock 'ci2'
        $l = Run-Job 'launch visible=1 owner=ci2' 'launch' 40
        Assert-Eq $l.d.status 'ok' "launch ($($l.out))"; Assert-Match $l.out 'running: FakeGame.exe pid \d+' 'pid confirmed'
        Assert-True ((Fake-Procs).Count -eq 1) 'running'
        Wait-Until { (Get-St).game_state.state -eq 'running' } 10 'status says running' | Out-Null
        $l2 = Run-Job 'launch visible=1 owner=ci2' 'launch2'
        Assert-Eq $l2.d.status 'refused' 'second launch'; Assert-Match $l2.d.reason 'already running' 'reason'
        $k = Run-Job 'kill owner=ci2' 'kill' 40
        Assert-Eq $k.d.status 'ok' 'kill'; Assert-True ((Fake-Procs).Count -eq 0) 'gone'
        $e = Start-Process -FilePath (Join-Path $game 'FakeOther.exe') -ArgumentList 'idle' -PassThru
        $l3 = Run-Job 'launch visible=1 owner=ci2' 'other'
        Assert-Eq $l3.d.status 'refused' 'the other title is running'; Assert-Match $l3.d.reason 'FakeOther.exe' 'names it'
        Stop-Process -Id $e.Id -Force
        $fl = $A_foreign = (Get-Content -LiteralPath $adapterPath -Raw | ConvertFrom-Json).foreign_locks[0]
        New-Item -ItemType Directory -Path (Split-Path $fl) -Force | Out-Null
        [IO.File]::WriteAllText($fl, "owner=other-agent session=e purpose=probe started=$(UtcNow-Str)`r`n", $Utf8NoBom)
        $l4 = Run-Job 'launch visible=1 owner=ci2' 'foreign'
        Assert-Eq $l4.d.status 'refused' 'foreign lock'; Assert-Match $l4.d.reason 'another watcher' 'reason'
        Assert-Match ([IO.File]::ReadAllText($fl)) 'other-agent' 'the foreign lock was only read'
        Remove-Item -LiteralPath $fl -Force
        # J12 fix 1g: stale VirtualStore copies of a guarded folder are moved aside before the launch, whoever asks for it
        $vsd = Join-Path (Join-Path $env:WSP_VIRTUALSTORE_ROOT (Split-Path -NoQualifier $game)) 'testmod'
        New-Item -ItemType Directory -Path (Join-Path $vsd 'logs') -Force | Out-Null
        [IO.File]::WriteAllText((Join-Path $vsd 'headless_status.json'), '{}', $Utf8NoBom); [IO.File]::WriteAllText((Join-Path $vsd 'logs\x.log'), 'x', $Utf8NoBom)
        $l5 = Run-Job 'launch visible=1 owner=ci2' 'launchvs' 40
        Assert-Eq $l5.d.status 'ok' "launch after the VirtualStore guard ($($l5.out))"
        Assert-Match $l5.out 'virtualstore: moved 2 stale file\(s\) of testmod aside' 'the copies are named in the output'
        Assert-True (@(Get-ChildItem -LiteralPath $vsd -Recurse -File).Count -eq 0) 'no copy left in the VirtualStore'
        Assert-True (@(Get-ChildItem -LiteralPath (Join-Path $root '_to_delete') -Recurse -File -Filter 'headless_status.json').Count -ge 1) 'moved, never deleted'
        Assert-Eq (Run-Job 'kill owner=ci2' 'killvs' 40).d.status 'ok' 'kill after the VirtualStore case'
        Clear-Lock
    }
    # ---- headless launch (J13): the watcher side. A fake game writes the proxy's headless_status.json itself. -----------------------------------
    $hdll = Join-Path $game 'd3d9.dll'
    $hstat = Join-Path $game 'testmod\headless_status.json'
    $vdDir = $tmp
    function Set-Vd([string]$state, [string]$offered = '3840x2160') {
        [IO.File]::WriteAllText((Join-Path $vdDir 'vd_state.txt'), $state, $Utf8NoBom); [IO.File]::WriteAllText((Join-Path $vdDir 'vd_offered.txt'), $offered, $Utf8NoBom)
        Remove-Item -LiteralPath (Join-Path $vdDir 'vd_calls.txt') -Force -ErrorAction SilentlyContinue
    }
    function Vd-State { return ([IO.File]::ReadAllText((Join-Path $vdDir 'vd_state.txt'))).Trim() }
    function Vd-Calls { $p = Join-Path $vdDir 'vd_calls.txt'; if (Test-Path -LiteralPath $p) { return [IO.File]::ReadAllText($p) } else { return '' } }
    function Set-Proxy([bool]$withMarker) {
        [IO.File]::WriteAllBytes($hdll, [Text.Encoding]::ASCII.GetBytes($(if ($withMarker) { 'MZ fake proxy ... testmod\headless_status.json ...' } else { 'MZ fake old proxy' })))
    }
    function Write-HStatus([int]$p, [string]$state, [string]$detail = '') {
        New-Item -ItemType Directory -Path (Split-Path $hstat) -Force | Out-Null
        $o = [ordered]@{ pid = $p; launch_id = 'ci'; state = $state; detail = $detail; target = [ordered]@{ device = '\\.\DISPLAY10'; adapter = 'Virtual Display Driver'; rect = @(3839, 2160, 7679, 4320) }
            window = @(3840, 2160); client = @(3840, 2160); backbuffer = @(3840, 2160); exit_code = $(if ($state -eq 'refused') { 2160 } else { 0 }); written_utc = (UtcNow-Str) }
        [IO.File]::WriteAllText("$hstat.tmp", ($o | ConvertTo-Json -Depth 4), $Utf8NoBom); Move-Item -LiteralPath "$hstat.tmp" -Destination $hstat -Force
    }
    function Wait-FakePid { return [int](Wait-Until { $x = Fake-Procs; if ($x.Count) { $x[0].Id } } 40 'the fake game to start') }
    function Real-Prefs {
        $t = "write_preferences_at_exit true; # write_preferences_at_exit <bool>, Write preferences at exit #`r`nx_res 3840; # x_res <int32>, Fixed window width #`r`ny_res 2160; # y_res <int32>, Fixed window height #`r`nx_pos 0; # x_pos <int32>, Window position #`r`ny_pos 0; # y_pos <int32>, Window position #`r`ngfx_fullscreen true; # gfx_fullscreen <bool>, Run the application in fullscreen or not #`r`n"
        return ([byte[]]@(0xFF, 0xFE) + (New-Object Text.UnicodeEncoding($false, $false)).GetBytes($t))
    }
    $oddPrefs = [byte[]](0, 255, 13, 10, 10, 13, 0xC3, 0xA9, 200, 1, 2, 3)
    function Latest-Probe { return (Get-ChildItem (Join-Path $root 'runs') -Directory -Filter '*_winprobe' | Sort-Object Name | Select-Object -Last 1) }

    Test-Case 'headless launch: on_virtual = ok; the display is checked, prefs and mod ini overlaid on top (profile-style snapshot), the window probe measures the launch, files come back byte for byte' {
        Set-Lock 'ci9'; Set-Vd '3840x2160'; Set-Proxy $true; Remove-Item -LiteralPath $hstat -Force -ErrorAction SilentlyContinue
        [IO.File]::WriteAllBytes($prefs, (Real-Prefs)); $h0 = Hashes
        $id = Submit 'launch owner=ci9 headless_wait_s=60' (New-JobId 'hl')
        $p = Wait-FakePid
        Write-HStatus $p 'starting'; Start-Sleep -Milliseconds 700
        Write-HStatus $p 'on_virtual' 'window on the virtual display'
        $r = Get-Result $id 60
        Assert-Eq $r.d.status 'ok' "launch ($($r.out))"
        Assert-Match $r.out 'headless: VIRTUAL OK' 'display checked'
        Assert-Match $r.out 'headless overlay prefs' 'prefs overlaid'; Assert-Match $r.out 'headless overlay mod_ini' 'mod ini overlaid'
        Assert-Match $r.out 'snapshot: profiles' 'snapshot taken like a profile'
        Assert-Match $r.out 'window probe: runs\\\d+T\d+Z_winprobe' 'the probe folder is named'
        Assert-Match $r.out 'headless: on_virtual \(target \\\\\.\\DISPLAY10 rect 3839,2160,7679,4320, window 3840x2160' 'status details'
        $pt = [Text.Encoding]::Unicode.GetString([IO.File]::ReadAllBytes($prefs), 2, [IO.File]::ReadAllBytes($prefs).Length - 2)
        Assert-Match $pt 'x_res 3840; # x_res <int32>, Fixed window width #' 'x_res value in place, comment kept'
        Assert-Match $pt 'gfx_fullscreen false; # gfx_fullscreen <bool>' 'windowed'
        Assert-Match (ReadText $modIni) '(?s)\[headless\].*enabled=1.*size=3840x2160' 'proxy keys written'
        Wait-Until { (Get-St).profile_active -and (Get-St).profile_active.name -eq 'headless' } 10 'status shows the headless overlay active' | Out-Null
        $probe = Latest-Probe
        Assert-True (Test-Path -LiteralPath (Join-Path $probe.FullName 'ready.txt')) 'the probe was polling before the game started'
        Run-Job 'kill owner=ci9' 'hlk' 40 | Out-Null
        Wait-Until { Test-Path -LiteralPath (Join-Path $probe.FullName 'winprobe.json') } 40 'winprobe.json' | Out-Null
        $wp = (ReadText (Join-Path $probe.FullName 'winprobe.json')) | ConvertFrom-Json
        Assert-True ([bool]$wp.started) 'the probe saw the game'; Assert-True ($wp.samples -gt 5) 'sampled'
        foreach ($k in 'longest_visible_on_real_ms', 'visible_on_real_ms_total', 'visible_on_real_samples', 'visible_off_target_count', 'cloaked_ms', 'monitor_changes', 'first_visible', 'windows', 'topology_start', 'topology_end', 'duration_ms') {
            Assert-True ($wp.PSObject.Properties.Name -contains $k) "winprobe.json has $k"
        }
        Assert-True (@($wp.topology_start).Count -ge 1) 'topology recorded at the start'
        Clear-Lock
        Wait-Until { (Hashes) -eq $h0 } 30 'lock release restores every file' | Out-Null
        Wait-LogMatch 'AUTO-RESTORE under owner=ci9' 10 'restore logged'
        Assert-True (-not (Test-Path -LiteralPath $modIni)) 'mod ini absent again'
        [IO.File]::WriteAllBytes($prefs, $oddPrefs)
        Remove-Item -LiteralPath $hdll, $hstat -Force -ErrorAction SilentlyContinue
        Assert-Eq (Hashes) $baseline 'suite baseline back'
    }
    Test-Case 'headless launch: a virtual display at another size is set (previous mode saved), kept while the lock is held, restored when it is released; a size the driver does not offer is refused with nothing started' {
        Set-Lock 'ci10'; Set-Vd '3840x2160' '3840x2160,1920x1080'; Set-Proxy $true; Remove-Item -LiteralPath $hstat -Force -ErrorAction SilentlyContinue
        [IO.File]::WriteAllBytes($prefs, (Real-Prefs)); $h0 = Hashes
        $id = Submit 'launch owner=ci10 size=1920x1080 headless_wait_s=60' (New-JobId 'hs')
        $p = Wait-FakePid
        Write-HStatus $p 'on_virtual'
        $r = Get-Result $id 60
        Assert-Eq $r.d.status 'ok' "launch ($($r.out))"
        Assert-Match $r.out 'setting 1920x1080' 'the watcher set the size'
        Assert-Eq (Vd-State) '1920x1080' 'virtual display now 1080p'
        Assert-True (Test-Path -LiteralPath (Join-Path $root 'vdisplay_restore.json')) 'previous mode saved'
        Assert-Match (ReadText $modIni) 'size=1920x1080' 'proxy key carries the size'
        Assert-Match ([Text.Encoding]::Unicode.GetString([IO.File]::ReadAllBytes($prefs))) 'x_res 1920;' 'prefs carry the size'
        Run-Job 'kill owner=ci10' 'hsk' 40 | Out-Null
        # the mode stays while the lock is held (every mode change moves Liam's cursor): a second launch at the size changes nothing
        Start-Sleep -Seconds 3
        Assert-Eq (Vd-State) '1920x1080' 'still 1080p after the game exited, lock held'
        $id2 = Submit 'launch owner=ci10 size=1920x1080 headless_wait_s=60' (New-JobId 'hs2')
        $p2 = Wait-FakePid
        Write-HStatus $p2 'on_virtual'
        $r2 = Get-Result $id2 60
        Assert-Eq $r2.d.status 'ok' "second launch ($($r2.out))"
        Assert-True ($r2.out -notmatch 'setting 1920x1080') 'no second mode change'
        Run-Job 'kill owner=ci10' 'hsk2' 40 | Out-Null
        Clear-Lock
        Wait-Until { (Vd-State) -eq '3840x2160' } 30 'previous mode restored after the lock was released' | Out-Null
        Wait-Until { -not (Test-Path -LiteralPath (Join-Path $root 'vdisplay_restore.json')) } 10 'restore file moved away' | Out-Null
        Wait-LogMatch 'vdisplay: previous mode restored' 10 'restore logged'
        Wait-Until { (Hashes) -eq $h0 } 30 'files restored' | Out-Null
        # not offered: refused before anything starts, nothing overlaid
        Set-Lock 'ci10'; Remove-Item -LiteralPath $hstat -Force -ErrorAction SilentlyContinue
        $n = Run-Job 'launch owner=ci10 size=2560x1440' 'hsn' 60
        Assert-Eq $n.d.status 'refused' "not offered ($($n.out))"; Assert-Match $n.d.reason 'MODE NOT OFFERED' 'says why'
        Assert-True ((Fake-Procs).Count -eq 0) 'no game started'
        Wait-Until { $s = Get-St; $s -and -not $s.profile_active } 20 'nothing overlaid' | Out-Null
        Assert-Eq (Vd-State) '3840x2160' 'display untouched'
        Clear-Lock
        [IO.File]::WriteAllBytes($prefs, $oddPrefs); Remove-Item -LiteralPath $hdll -Force -ErrorAction SilentlyContinue
    }
    Test-Case 'headless launch: no virtual display, or a proxy without the status-file marker, is refused before the game starts (fail closed)' {
        Set-Lock 'ci11'; Set-Vd 'none'; Set-Proxy $true
        $r = Run-Job 'launch owner=ci11' 'hnv' 60
        Assert-Eq $r.d.status 'refused' "no display ($($r.out))"; Assert-Match $r.d.reason 'no virtual display at 3840x2160.*VIRTUAL MISSING' 'names the tool message'
        Assert-True ((Fake-Procs).Count -eq 0) 'no game started'
        Set-Vd '3840x2160'; Set-Proxy $false
        $m = Run-Job 'launch owner=ci11' 'hnm' 60
        Assert-Eq $m.d.status 'refused' 'old proxy'; Assert-Match $m.d.reason 'cannot run headless' 'says so'
        Assert-True ((Fake-Procs).Count -eq 0) 'no game started'
        Wait-Until { $s = Get-St; $s -and -not $s.profile_active } 20 'nothing overlaid' | Out-Null
        Assert-Eq (Hashes) $baseline 'no config touched'
        Assert-Eq (Run-Job 'launch owner=ci11 size=1080p' 'hbs' 20).d.status 'refused' 'a bad size is refused'
        Clear-Lock; Remove-Item -LiteralPath $hdll -Force -ErrorAction SilentlyContinue
    }
    Test-Case 'headless launch: the proxy refusing (status refused, exit 2160) fails the job with the detail; no status in time kills the game' {
        Set-Lock 'ci12'; Set-Vd '3840x2160'; Set-Proxy $true; Remove-Item -LiteralPath $hstat -Force -ErrorAction SilentlyContinue
        [IO.File]::WriteAllBytes($prefs, (Real-Prefs)); $h0 = Hashes
        $id = Submit 'launch owner=ci12 headless_wait_s=60' (New-JobId 'hr')
        $p = Wait-FakePid
        Write-HStatus $p 'refused' 'no target: the virtual display is gone'
        Stop-Process -Id $p -Force
        $r = Get-Result $id 60
        Assert-Eq $r.d.status 'failed' "refused ($($r.out))"
        Assert-Match $r.d.reason 'HEADLESS FAILED: the proxy refused the launch: no target: the virtual display is gone \(exit code 2160' 'detail and exit code in the reason'
        # a stale status of an old pid is ignored; silence is fail closed
        Remove-Item -LiteralPath $hstat -Force -ErrorAction SilentlyContinue
        $t = Run-Job 'launch owner=ci12 headless_wait_s=4' 'hrt' 60
        Assert-Eq $t.d.status 'failed' 'timeout'; Assert-Match $t.d.reason 'no on_virtual status.*within 4 s.*killed' 'timeout reason'
        Wait-Until { (Fake-Procs).Count -eq 0 } 20 'the game was killed' | Out-Null
        Clear-Lock; Wait-Until { (Hashes) -eq $h0 } 30 'files restored after failed launches' | Out-Null
        [IO.File]::WriteAllBytes($prefs, $oddPrefs); Remove-Item -LiteralPath $hdll, $hstat -Force -ErrorAction SilentlyContinue
    }
    Test-Case 'visible=1: no overlay, no display check, no status wait; the launch is still measured by the window probe' {
        Set-Lock 'ci13'; Set-Vd 'none'; Remove-Item -LiteralPath $hdll, $hstat -Force -ErrorAction SilentlyContinue
        $h0 = Hashes
        $r = Run-Job 'launch visible=1 owner=ci13' 'hv' 60
        Assert-Eq $r.d.status 'ok' "visible launch ($($r.out))"
        Assert-Match $r.out 'visible launch: no config touched' 'says so'; Assert-Match $r.out 'window probe: runs' 'probe started'
        Assert-NotMatch $r.out 'headless' 'no headless step ran'
        Assert-Eq (Hashes) $h0 'no file changed'; Wait-Until { $s = Get-St; $s -and -not $s.profile_active } 20 'no profile or overlay recorded' | Out-Null
        Assert-Eq (Vd-Calls) '' 'the display tool was not called'
        Run-Job 'kill owner=ci13' 'hvk' 40 | Out-Null
        Clear-Lock
    }
    Test-Case 'zombie: a process that survives the kill is flagged, persisted across a watcher restart, every launch refused until it is gone' {
        $mark = Log-Mark
        Add-Content -LiteralPath (Join-Path $root 'watcher.ini') -Value "`r`ntest_fake_zombie=1" -Encoding Ascii
        Wait-Until { (Get-LogSince $mark) -match 'settings: watcher.ini reloaded' } 10 'ini reloaded' | Out-Null
        Start-Sleep -Milliseconds 600
        Set-Lock 'ci3'
        $l = Run-Job 'launch visible=1 owner=ci3' 'zlaunch' 40; Assert-Eq $l.d.status 'ok' 'launch'
        $k = Run-Job 'kill owner=ci3' 'zkill' 40
        Assert-Eq $k.d.status 'failed' 'kill fails'; Assert-Match $k.d.reason 'ZOMBIE' 'reason'
        Wait-Until { $x = Get-St; $x -and [bool]$x.zombie -and [bool]$x.needs_reboot } 15 'status shows zombie and needs_reboot' | Out-Null
        $r = Run-Job 'launch visible=1 owner=ci3' 'zrefuse'
        Assert-Eq $r.d.status 'failed' 'launch is refused loudly (failed, exit 1) so no agent mistakes it for a policy refusal'; Assert-Match $r.d.reason 'PC NEEDS REBOOT' 'says the PC needs a reboot'
        Assert-True (Test-Path -LiteralPath (Join-Path $root 'watcher.zombie.json')) 'persisted'
        $old = Pid-Of-Watcher
        Run-Job 'restart' 'zrestart' | Out-Null
        Wait-Until { (Alive-Age) -lt 4 -and (Pid-Of-Watcher) -ne $old } 40 'a new watcher process' | Out-Null
        Assert-True ([bool](Get-St).zombie) 'the zombie flag survived the restart'
        Stop-Fakes
        Wait-Until { -not (Get-St).zombie } 15 'flag clears once the pid is gone' | Out-Null
        Assert-Match (Get-Log) 'is gone - launches allowed again' 'logged'
        $ini2 = (ReadText (Join-Path $root 'watcher.ini')).Replace('test_fake_zombie=1', 'test_fake_zombie=0')
        [IO.File]::WriteAllText((Join-Path $root 'watcher.ini'), $ini2, $Utf8NoBom)
        Start-Sleep -Seconds 2
        Clear-Lock
    }
    Test-Case 'profiles through the watcher: apply, switch, game running refuses, restore is byte-identical (absent files too)' {
        Set-Lock 'ci4'
        $p = Run-Job 'profile proxy-dxvk owner=ci4' 'prof'
        Assert-Eq $p.d.status 'ok' "apply ($($p.out))"; Assert-Match $p.out 'snapshot: profiles' 'snapshot taken'
        Assert-Match (ReadText $modIni) '(?m)^backend=dxvk' 'overlay applied to the absent ini'
        $l = Run-Job 'launch visible=1 owner=ci4' 'plaunch' 40; Assert-Eq $l.d.status 'ok' 'launch'
        $sw = Run-Job 'profile vanilla owner=ci4' 'pswitch'
        Assert-Eq $sw.d.status 'refused' 'switch while running'; Assert-Match $sw.d.reason 'already running' 'reason'
        Run-Job 'kill owner=ci4' 'pkill' 40 | Out-Null
        $sw = Run-Job 'profile vanilla owner=ci4' 'pswitch2'; Assert-Eq $sw.d.status 'ok' 'switch'
        Assert-True (-not (Test-Path -LiteralPath $modIni)) 'vanilla: no mod ini'
        $r = Run-Job 'profile restore owner=ci4' 'prest'
        Assert-Eq $r.d.status 'ok' "restore ($($r.out))"; Assert-Eq (Hashes) $baseline 'every file byte-identical to the baseline'
        Clear-Lock
    }
    Test-Case 'auto-restore: lock expiry, release, owner change, and deferral while the game runs; each says so in the log' {
        # repeat-safe (J42): log waits read only lines after this mark, and the moved-lock count is relative
        $mark = Log-Mark; $expired = @(Get-ChildItem (Join-Path $root '_to_delete') -Filter 'game.lock.expired_ci5_*' -ErrorAction SilentlyContinue).Count
        # a) expiry, with a profile active: restored UNDER ITS OWNER and logged
        Set-Lock 'ci5'; Run-Job 'profile proxy-dxvk owner=ci5' 'a1' | Out-Null
        Assert-True ((Hashes) -ne $baseline) 'profile applied'
        (Get-Item -LiteralPath (Join-Path $root 'game.lock')).LastWriteTime = (Get-Date).AddMinutes(-25)
        Wait-Until { (Hashes) -eq $baseline } 20 'restored after expiry' | Out-Null
        # the files are restored BEFORE the AUTO-RESTORE line is written: wait for the line, never read the log once (J2 review, run 40832860145)
        Wait-LogMatch 'LOCK EXPIRED: game.lock owner=ci5' 10 'expiry logged' -Since $mark
        Wait-LogMatch 'AUTO-RESTORE under owner=ci5' 10 'restore under the owner is logged' -Since $mark
        Assert-True (@(Get-ChildItem (Join-Path $root '_to_delete') -Filter 'game.lock.expired_ci5_*').Count -eq $expired + 1) 'lock moved, not deleted'
        # b) release
        Set-Lock 'ci6'; Run-Job 'profile proxy-dxvk owner=ci6' 'b1' | Out-Null; Clear-Lock
        Wait-Until { (Hashes) -eq $baseline } 20 'restored after release' | Out-Null
        Wait-LogMatch 'AUTO-RESTORE under owner=ci6 .*released or expired' 10 'release logged' -Since $mark
        # c) changes owner
        Set-Lock 'ci7'; Run-Job 'profile proxy-dxvk owner=ci7' 'c1' | Out-Null
        # a lock mid-rewrite (0 bytes) is not a release: no restore on it
        [IO.File]::WriteAllBytes((Join-Path $root 'game.lock'), [byte[]]@()); Start-Sleep -Seconds 5
        Assert-True ((Hashes) -ne $baseline) 'a 0-byte lock (mid-rewrite) does not trigger a restore'
        Set-Lock 'intruder'
        Wait-Until { (Hashes) -eq $baseline } 20 'restored after the owner changed' | Out-Null
        Wait-LogMatch "AUTO-RESTORE under owner=ci7 .*now belongs to 'intruder'" 10 'owner change logged' -Since $mark
        Clear-Lock
        # d) deferred while the game runs
        Set-Lock 'ci8'; Run-Job 'profile proxy-dxvk owner=ci8' 'd1' | Out-Null
        $idleGame = Start-Process -FilePath (Join-Path $game 'FakeGame.exe') -ArgumentList 'idle' -PassThru
        Clear-Lock
        Wait-Until { (Get-LogSince $mark) -match "auto-restore of 'proxy-dxvk' \(owner=ci8\) pending" } 15 'pending is logged' | Out-Null
        Assert-True ((Hashes) -ne $baseline) 'not restored while the game is open'
        Stop-Process -Id $idleGame.Id -Force
        Wait-Until { (Hashes) -eq $baseline } 20 'restored once the game exited' | Out-Null
    }
    Test-Case 'hang watchdog: a suspended game is caught (no CPU, no log write), minidumped out of process, archived, killed; busy and unarmed games are left alone' {
        Remove-Item -LiteralPath $logPath -Force -ErrorAction SilentlyContinue
        $mark = Log-Mark
        $runsBefore = @(Get-ChildItem (Join-Path $root 'runs') -Directory -Filter '*_hang' -ErrorAction SilentlyContinue | ForEach-Object { $_.Name })
        # unarmed: no lock, no watcher launch -> a game Liam started himself is never touched
        Clear-Lock
        $u = Start-Process -FilePath (Join-Path $game 'FakeGame.exe') -ArgumentList 'idle' -PassThru
        Start-Sleep -Seconds 11
        Assert-True (-not $u.HasExited) 'an unarmed idle game is left alone'
        Stop-Process -Id $u.Id -Force; Start-Sleep -Seconds 1
        # armed (valid lock, hang_s=6): CPU-busy game with no log is alive
        Set-Lock 'ci9' ' hang_s=6'
        $s = Start-Process -FilePath (Join-Path $game 'FakeGame.exe') -ArgumentList 'spin' -PassThru
        Start-Sleep -Seconds 11
        Assert-True (-not $s.HasExited) 'a game that burns CPU is alive'
        Stop-Process -Id $s.Id -Force; Start-Sleep -Seconds 1
        # armed, log writer (no CPU to speak of): alive, then frozen
        $h = Start-Process -FilePath (Join-Path $game 'FakeGame.exe') -ArgumentList "log `"$logPath`"" -PassThru
        Start-Sleep -Seconds 10
        Assert-True (-not $h.HasExited) 'a game that keeps writing its log is alive'
        $fz = Run-Job "#job type=ps1 owner=ci9`r`n& `"$(Join-Path $root 'src\procfreeze.ps1')`" -ProcessId $($h.Id) -Mode suspend" 'freeze' 30
        Assert-Eq $fz.d.status 'ok' "freeze ($($fz.out))"
        Wait-Until { $h.Refresh(); $h.HasExited } 90 'the hung game to be killed' | Out-Null
        # the process can be gone while the watcher is still in Kill-Game's polling loop: its log line is the completion signal (J19, run 40878131007)
        Wait-LogMatch 'HANG handled: killed' 30 'the watcher to finish handling the hang' -Since $mark
        $runs = @(Get-ChildItem (Join-Path $root 'runs') -Directory -Filter '*_hang' | Where-Object { $runsBefore -notcontains $_.Name })
        Assert-True ($runs.Count -eq 1) "one new runs\<utc>_hang folder (got $($runs.Count))"
        $dir = $runs[0].FullName
        $dmp = @(Get-ChildItem $dir -Filter '*.dmp')
        Assert-True ($dmp.Count -eq 1 -and $dmp[0].Length -gt 4096) 'a real minidump was written'
        Assert-Eq ([Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($dmp[0].FullName)[0..3])) 'MDMP' 'dump signature (32-bit target dumped by the SysWOW64 helper)'
        Assert-True (Test-Path -LiteralPath (Join-Path $dir 'hang.txt')) 'hang.txt'
        $hangTxt = ReadText (Join-Path $dir 'hang.txt')
        Assert-Match $hangTxt 'no CPU-time progress' 'reason in hang.txt'
        Assert-Match $hangTxt '(?m)^kill: killed\s*$' 'hang.txt holds the kill result'
        Assert-NotMatch $hangTxt 'kill: pending' 'hang.txt was rewritten after the kill'
        Assert-True (@(Get-ChildItem $dir -Filter '*proxy.log').Count -eq 1) 'the proxy log was archived'
        Assert-True (Test-Path -LiteralPath (Join-Path $dir 'game.lock')) 'the lock was archived'
        Assert-Match (Get-LogSince $mark) 'HANG: FakeGame.exe' 'logged'
        Wait-Until { $x = Get-St; $x -and $x.last_hang -and [bool]$x.last_hang.killed } 15 'status.last_hang.killed' | Out-Null
        Assert-True ((Fake-Procs).Count -eq 0) 'process gone'
        Clear-Lock
    }
    Test-Case 'dump.ps1 also dumps a 64-bit process' {
        $p = Start-Process -FilePath (Join-Path $tmp 'Fake64.exe') -ArgumentList 'idle' -PassThru
        $out = Join-Path $tmp 'x64.dmp'
        $o = & (Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe') -NoProfile -ExecutionPolicy Bypass -File (Join-Path $core 'dump.ps1') -ProcessId $p.Id -Out $out
        Stop-Process -Id $p.Id -Force
        Assert-Eq $LASTEXITCODE 0 "exit code ($o)"; Assert-True ((Get-Item -LiteralPath $out).Length -gt 4096) 'dump written'
    }
    Test-Case 'long-lived processes start detached: spawn_detached leaves no handle on the job output; the display probe only validates' {
        $mk = Join-Path $tmp 'later.cmd'
        [IO.File]::WriteAllText($mk, "@echo off`r`nping -n 6 127.0.0.1 >nul`r`necho done> `"$tmp\later.marker`"`r`n", [Text.Encoding]::ASCII)
        $r = Run-Job "#ps1`r`n& `"$(Join-Path $root 'src\spawn_detached.ps1')`" -Path `"$mk`"" 'spawn' 30
        Assert-Eq $r.d.status 'ok' "spawn ($($r.out))"; Assert-Match $r.out 'spawned pid=\d+ rc=0' 'spawned'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $root "jobs\$($r.id).part"))) 'the job output .part was released (no inherited handle)'
        Wait-Until { Test-Path -LiteralPath (Join-Path $tmp 'later.marker') } 30 'the detached process to finish on its own' | Out-Null
        $v = Run-Job "#ps1`r`n& `"$(Join-Path $root 'src\vdisplay_probe.ps1')`"" 'vd' 60
        Assert-Match $v.out 'displays \(' 'lists the displays'
        Assert-True ($v.out -match 'NO UNIQUE VIRTUAL DISPLAY' -or $v.out -match 'mode list' ) 'either no virtual display (the runner) or a mode list'
        Assert-NotMatch $v.out 'ChangeDisplaySettingsEx\(.*-> 0 .*applied' 'nothing applied'
        $c = Run-Job "#ps1`r`n& `"$(Join-Path $root 'src\vdisplay_probe.ps1')`" -Check -Size 3840x2160" 'vdc' 60
        Assert-Match $c.out 'VIRTUAL (OK|MISSING|WRONG SIZE)' '-Check says which'
        $s = Run-Job "#ps1`r`n& `"$(Join-Path $root 'src\vdisplay_probe.ps1')`" -Set 1920x1080" 'vds' 60
        Assert-Match $s.out 'bad arguments: this mode needs -SaveTo|VIRTUAL MISSING' "-Set without -SaveTo never reaches the apply ($($s.out))"
    }
    Test-Case 'launcher restarts the watcher after a crash, and the job that was running is closed as lost' {
        $old = Pid-Of-Watcher
        $id = Submit "@echo off`r`nping -n 40 127.0.0.1 >nul`r`necho never" (New-JobId 'lost')
        Wait-Until { (Get-St).current_job.id -eq $id } 20 'job running' | Out-Null
        Stop-Process -Id $old -Force
        Wait-Until { (Alive-Age) -lt 4 -and (Pid-Of-Watcher) -ne $old } 60 'the launcher to bring a new watcher up' | Out-Null
        $r = Get-Result $id 30
        Assert-Eq $r.d.status 'lost' 'the interrupted job is closed as lost'
        Get-Process -Name ping -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
        Assert-Eq (Run-Job 'noop' 'afterlost').d.status 'ok' 'and the queue works'
    }

    # ---- update with a dead-man switch --------------------------------------------------------------------------------------------
    function New-TestKit([string]$id, [hashtable]$over) {
        $kd = Join-Path $kits $id; New-Item -ItemType Directory -Path $kd -Force | Out-Null
        $entries = @()
        foreach ($f in Get-ChildItem (Join-Path $root 'src') -File) {
            $bytes = if ($over.ContainsKey($f.Name)) { [byte[]]$over[$f.Name] } else { [IO.File]::ReadAllBytes($f.FullName) }
            $h = (New-Object Security.Cryptography.SHA256Managed).ComputeHash($bytes); $sha = ([BitConverter]::ToString($h)).Replace('-', '').ToLower()
            $staged = "$($sha.Substring(0, 12))__src__$($f.Name)"
            [IO.File]::WriteAllBytes((Join-Path $kd $staged), $bytes)
            $entries += [ordered]@{ path = "src/$($f.Name)"; staged = $staged; sha256 = $sha; size = $bytes.Length; role = 'test' }
        }
        $w = [Text.Encoding]::ASCII.GetString([byte[]]$(if ($over.ContainsKey('watcher.ps1')) { $over['watcher.ps1'] } else { [IO.File]::ReadAllBytes((Join-Path $root 'src\watcher.ps1')) }))
        $ver = [regex]::Match($w, "\`$Version = '([^']+)'").Groups[1].Value
        $man = [ordered]@{ kind = 'harness'; kit_id = $id; watcher_version = $ver; files = $entries; kit_files = @() }
        [IO.File]::WriteAllText((Join-Path $kd 'manifest.json'), ($man | ConvertTo-Json -Depth 5), $Utf8NoBom)
        return $ver
    }
    function Watcher-Text { return [Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes((Join-Path $root 'src\watcher.ps1'))) }
    Test-Case 'update: a good kit replaces the watcher, the new one answers noop, the update is confirmed' {
        $cur = Watcher-Text
        # any current version: a literal '1.0.0' here made every watcher version bump silently break this case (J19)
        $ver = New-TestKit 'kit-good' @{ 'watcher.ps1' = [Text.Encoding]::ASCII.GetBytes(([regex]"\`$Version = '[^']+'").Replace($cur, "`$Version = '9.9.9-ci'", 1)) }
        Assert-Eq $ver '9.9.9-ci' 'kit version'
        $mark = Log-Mark
        $r = Run-Job 'update kit=kit-good noop_s=40 healthy_s=60 stable_s=5' 'upd' 30
        Assert-Eq $r.d.status 'ok' "update accepted ($($r.out))"
        Wait-Until { (Alive-Age) -lt 4 -and (Get-St).version -eq '9.9.9-ci' } 120 'the new version' | Out-Null
        Wait-Until { (Get-LogSince $mark) -match '\[update\] CONFIRMED' } 90 'CONFIRMED' | Out-Null
        Assert-Match (Watcher-Text) "9\.9\.9-ci" 'file replaced'
        Assert-True (@(Get-ChildItem (Join-Path $root 'backup') -Directory).Count -ge 1) 'a backup of the old files exists'
        Assert-Eq (Run-Job 'noop' 'afterupd').d.status 'ok' 'new watcher serves jobs'
    }
    Test-Case 'update rollback 1: a watcher that does not start is put back byte for byte' {
        $mark = Log-Mark   # repeat-safe (J42 run 40968854173: run 2 matched run 1's REVERTED line and passed in 4 s)
        $before = Sha256File (Join-Path $root 'src\watcher.ps1')
        $bad = (Watcher-Text).Replace("`$Version = '9.9.9-ci'", "`$Version = '9.9.7-bad'") + "`r`n)))`r`n"
        New-TestKit 'kit-bad' @{ 'watcher.ps1' = [Text.Encoding]::ASCII.GetBytes($bad) } | Out-Null
        Run-Job 'update kit=kit-bad noop_s=20 healthy_s=20 stable_s=3' 'updbad' 30 | Out-Null
        Wait-Until { (Get-LogSince $mark) -match 'REVERTED: watcher 9\.9\.9-ci' } 150 'the revert' | Out-Null
        Assert-Eq (Sha256File (Join-Path $root 'src\watcher.ps1')) $before 'src\watcher.ps1 is byte-identical to before'
        Wait-Until { (Alive-Age) -lt 4 -and (Get-St).version -eq '9.9.9-ci' } 60 'the old watcher back' | Out-Null
    }
    Test-Case 'update rollback 2: a new watcher that runs but does not answer a noop job is put back (the dead-man switch)' {
        $mark = Log-Mark
        $before = Sha256File (Join-Path $root 'src\watcher.ps1')
        $deaf = (Watcher-Text).Replace("`$Version = '9.9.9-ci'", "`$Version = '9.9.8-deaf'").Replace('function Start-NextJob {', 'function Start-NextJob { return $false')
        New-TestKit 'kit-deaf' @{ 'watcher.ps1' = [Text.Encoding]::ASCII.GetBytes($deaf) } | Out-Null
        Run-Job 'update kit=kit-deaf noop_s=10 healthy_s=60 stable_s=3' 'upddeaf' 30 | Out-Null
        Wait-Until { (Get-LogSince $mark) -match 'did not answer a noop job within 10 s' } 120 'the dead-man switch' | Out-Null
        Wait-Until { (Get-LogSince $mark) -match '(?s)did not answer a noop.*REVERTED: watcher 9\.9\.9-ci' } 90 'the revert' | Out-Null
        Assert-Eq (Sha256File (Join-Path $root 'src\watcher.ps1')) $before 'byte-identical after the revert'
        Wait-Until { (Alive-Age) -lt 4 -and (Get-St).version -eq '9.9.9-ci' } 60 'the old watcher back' | Out-Null
        Assert-Eq (Run-Job 'noop' 'afterdeaf').d.status 'ok' 'serving again'
    }
    Test-Case 'update refuses a stale or tampered kit before touching anything' {
        New-TestKit 'kit-stale' @{} | Out-Null
        $kd = Join-Path $kits 'kit-stale'
        $f = Get-ChildItem $kd -Filter '*__src__watcher.ps1' | Select-Object -First 1
        [IO.File]::WriteAllText($f.FullName, 'old cached copy', $Utf8NoBom)
        $before = Sha256File (Join-Path $root 'src\watcher.ps1')
        $mark = Log-Mark
        Run-Job 'update kit=kit-stale noop_s=10 healthy_s=20' 'updstale' 30 | Out-Null
        Wait-Until { (Get-LogSince $mark) -match 'ABORT: staged file .* does not match the manifest sha256' } 40 'the abort' | Out-Null
        Assert-Eq (Sha256File (Join-Path $root 'src\watcher.ps1')) $before 'nothing changed'
        $none = Run-Job 'update kit=no-such-kit' 'updnone' 20
        Assert-Eq $none.d.status 'refused' 'unknown kit'
    }
    Test-Case 'update: a kit whose files are all in place is NOTHING TO DO: no backup, no restart, never CONFIRMED (J2 L7)' {
        New-TestKit 'kit-same' @{} | Out-Null
        $pid0 = Pid-Of-Watcher; $baks = @(Get-ChildItem (Join-Path $root 'backup') -Directory -ErrorAction SilentlyContinue).Count
        $mark = Log-Mark
        Run-Job 'update kit=kit-same noop_s=10 healthy_s=20' 'updsame' 30 | Out-Null
        Wait-Until { (Get-LogSince $mark) -match 'NOTHING TO DO: every file of kit kit-same' } 40 'nothing to do' | Out-Null
        Assert-True (-not ((Get-LogSince $mark) -match '\[update\] (CONFIRMED|backup:)')) 'no backup and no CONFIRMED'
        Assert-Eq (Pid-Of-Watcher) $pid0 'the watcher was not restarted'
        Assert-Eq @(Get-ChildItem (Join-Path $root 'backup') -Directory -ErrorAction SilentlyContinue).Count $baks 'no new backup'
    }
    Test-Case 'update refuses a manifest whose kit_id is not its folder (J2 question 4)' {
        New-TestKit 'kit-copied' @{} | Out-Null
        $mf = Join-Path (Join-Path $kits 'kit-copied') 'manifest.json'
        [IO.File]::WriteAllText($mf, ([IO.File]::ReadAllText($mf) -replace '"kit_id":\s*"kit-copied"', '"kit_id": "kit-good"'), $Utf8NoBom)
        $mark = Log-Mark
        Run-Job 'update kit=kit-copied noop_s=10 healthy_s=20' 'updcopied' 30 | Out-Null
        Wait-Until { (Get-LogSince $mark) -match "ABORT: the manifest's kit_id 'kit-good' is not this kit's folder 'kit-copied'" } 40 'the abort' | Out-Null
    }
    Stop-TestWatcher
    Stop-Fakes

    # ---- installer, with the real kit built by pc_deploy.py ------------------------------------------------------------------------
    $py = (Get-Command python -ErrorAction SilentlyContinue)
    Test-Case 'installer: the real harness kit installs (sha-checked), registers the logon task, starts a healthy watcher; the uninstaller removes it' {
        Assert-True ($null -ne $py) 'python is needed for the real kit'
        $out = Join-Path $tmp 'realkits'
        & python (Join-Path $Repo 'proxy\tools\pc_deploy.py') kit --what harness --out $out | Out-Null
        Assert-Eq $LASTEXITCODE 0 'pc_deploy kit'
        $kit = (Get-ChildItem $out -Directory | Select-Object -First 1).FullName
        $iroot = Join-Path $tmp 'inst\watcher'
        $tn = 'testmod watcher citest'
        # a tampered staged file: refused, nothing installed
        $copy = Join-Path $tmp 'tamperedkit'; Copy-Item -LiteralPath $kit -Destination $copy -Recurse
        $m = (ReadText (Join-Path $copy 'manifest.json')) | ConvertFrom-Json
        [IO.File]::WriteAllText((Join-Path $copy $m.files[0].staged), 'stale', $Utf8NoBom)
        & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $copy 'install.ps1') -Kit $copy -Root (Join-Path $tmp 'inst_bad\watcher') -NoTask -NoStart | Out-Null
        Assert-True ($LASTEXITCODE -ne 0) 'tampered kit refused'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $tmp 'inst_bad\watcher\src\watcher.ps1'))) 'and nothing was installed'
        # the real install
        $o = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $kit 'install.ps1') -Kit $kit -Root $iroot -TaskName $tn
        Assert-Eq $LASTEXITCODE 0 "install exit ($($o -join ' | '))"
        $mm = (ReadText (Join-Path $kit 'manifest.json')) | ConvertFrom-Json
        foreach ($e in $mm.files) { Assert-Eq (Sha256File (Join-Path $iroot ($e.path -replace '/', '\'))) $e.sha256 "installed $($e.path)" }
        $t = Get-ScheduledTask -TaskName $tn
        Assert-True ($null -ne $t) 'task registered'
        Assert-Match ($t.Triggers[0].CimClass.CimClassName) 'Logon' 'logon trigger'
        Assert-Match $t.Actions[0].Arguments 'watch\.cmd' 'runs the launcher'
        Assert-True ((Alive-AgeOf $iroot) -lt 6) 'the watcher is running and reports itself'
        $res = (ReadText (Join-Path $iroot 'install_result.json')) | ConvertFrom-Json
        Assert-True ([bool]$res.ok) 'install_result.json ok'
        $again = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $kit 'install.ps1') -Kit $kit -Root $iroot -TaskName $tn
        Assert-True ($LASTEXITCODE -ne 0) 'a second install over a running watcher is refused (use update)'
        $u = & powershell.exe -NoProfile -ExecutionPolicy Bypass -File (Join-Path $kit 'install.ps1') -Kit $kit -Root $iroot -TaskName $tn -Uninstall
        Assert-Eq $LASTEXITCODE 0 "uninstall exit ($($u -join ' | '))"
        Assert-True ($null -eq (Get-ScheduledTask -TaskName $tn -ErrorAction SilentlyContinue)) 'task removed'
        Assert-True (-not (Test-Path -LiteralPath (Join-Path $iroot 'src'))) 'src moved away'
        Assert-True (@(Get-ChildItem (Join-Path $iroot '_to_delete') -Directory -Filter 'uninstall_*').Count -eq 1) 'moved to _to_delete, not deleted'
    }
}
finally {
    try { Stop-TestWatcher } catch { }
    Stop-Fakes
    Get-ScheduledTask -TaskName 'testmod watcher citest' -ErrorAction SilentlyContinue | Unregister-ScheduledTask -Confirm:$false -ErrorAction SilentlyContinue
    if ($SuiteState.tz) { & tzutil.exe /s $SuiteState.tz }
    if ($script:Fail) {
        Write-Host '---- watcher.log (last 120 lines) ----'
        try { (Get-Log) -split "`r?`n" | Select-Object -Last 120 | ForEach-Object { Write-Host $_ } } catch { }
        try { Get-ChildItem (Join-Path $tmp 'inst\watcher') -Filter '*.log' -ErrorAction SilentlyContinue | ForEach-Object { Write-Host "---- $($_.Name) ----"; Get-Content -LiteralPath $_.FullName -Tail 60 } } catch { }
    }
}
exit (Finish-Tests 'integration')
