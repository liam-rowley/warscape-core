# purpose: in-place update of the live watcher from a harness kit with a dead-man switch: the new watcher must come up, answer a noop job and stay alive, or the old files are put back byte for byte
# usage: started detached by the watcher's "update kit=<kit id>" job (exit 0 CONFIRMED, 1 REVERTED, 2 ABORT before any change, 3 revert copy failed, 4 NOTHING TO DO) (a copy of this file runs, because the update replaces src\update.ps1); by hand: powershell -File update.ps1 -Root <watcher root> -Kit <kit dir> [-NoopS 60] [-HealthyS 90] [-StableS 30]
# when: whenever harness files change on the PC after the first install (never copy them by hand); the first install is "Install watcher.cmd"
# not-a-verb: runs on the PC under Windows PowerShell 5.1, outside the repo checkout
param([Parameter(Mandatory = $true)][string]$Root, [Parameter(Mandatory = $true)][string]$Kit, [int]$NoopS = 60, [int]$HealthyS = 90, [int]$StableS = 30)
$ErrorActionPreference = 'Stop'
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/'); $Kit = [IO.Path]::GetFullPath($Kit).TrimEnd('\', '/')
$Utf8 = New-Object Text.UTF8Encoding $false
$Inv = [Globalization.CultureInfo]::InvariantCulture
$src = Join-Path $Root 'src'
$stamp = (Get-Date).ToUniversalTime().ToString('yyyyMMdd\THHmmss\Z', $Inv)
$bakDir = Join-Path (Join-Path $Root 'backup') $stamp
$ulog = Join-Path $PSScriptRoot 'update.log'
function Utc { return (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd\THH:mm:ss\Z', $Inv) }
function Log([string]$m) {
    $line = "[$(Utc)] [update] $m"
    for ($i = 0; $i -lt 10; $i++) { try { [IO.File]::AppendAllText((Join-Path $Root 'watcher.log'), "$line`r`n", $Utf8); break } catch { Start-Sleep -Milliseconds 50 } }
    try { [IO.File]::AppendAllText($ulog, "$line`r`n", $Utf8) } catch { }
}
function Sha([string]$p) { return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() }
# status can be caught mid-swap (it is replaced every 2 s): retry the read before believing it is broken
function Status {
    $p = Join-Path $Root 'watcher.status'
    for ($i = 0; $i -lt 8; $i++) {
        try {
            $fs = New-Object IO.FileStream($p, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]'ReadWrite,Delete')
            try { $ms = New-Object IO.MemoryStream; $fs.CopyTo($ms); $b = $ms.ToArray() } finally { $fs.Dispose() }
            if ($b.Length) { return ($Utf8.GetString($b) | ConvertFrom-Json) }
        } catch { }
        Start-Sleep -Milliseconds 100
    }
    return $null
}
# liveness from the heartbeat FILE's mtime, never from parsing watcher.status
function AliveAge { try { return ((Get-Date) - (Get-Item -LiteralPath (Join-Path $Root 'watcher.alive')).LastWriteTime).TotalSeconds } catch { return $null } }
function Watcher-Procs {
    $needle = (Join-Path $src 'watcher.ps1').ToLower()
    return @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" | Where-Object { $_.CommandLine -and $_.CommandLine.ToLower().Contains($needle) })
}
function Put([string]$from, [string]$to, [string]$want) {
    $dir = Split-Path $to; if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
    $tmp = "$to.updtmp"
    Copy-Item -LiteralPath $from -Destination $tmp -Force
    if ((Sha $tmp) -ne $want) { Remove-Item -LiteralPath $tmp -Force; throw "copy of $from does not verify" }
    if (Test-Path -LiteralPath $to) { [IO.File]::Replace($tmp, $to, [NullString]::Value) } else { [IO.File]::Move($tmp, $to) }
    if ((Sha $to) -ne $want) { throw "$to is not $want after the copy" }
}
function Submit-Noop {
    $id = "update-$stamp-noop"
    $jobs = Join-Path $Root 'jobs'
    [IO.File]::WriteAllText((Join-Path $jobs "$id.tmp"), "noop`r`n", $Utf8)
    Move-Item -LiteralPath (Join-Path $jobs "$id.tmp") -Destination (Join-Path $jobs "$id.request")
    return $id
}
$script:oldVersion = $null; $script:oldPid = 0
$script:Backed = @()      # [{rel, existed, sha}]
function Revert([string]$why) {
    Log "REVERTING to the backed-up files: $why"
    try {
        foreach ($b in $script:Backed) {
            $abs = Join-Path $Root $b.rel
            if ($b.existed) { Put (Join-Path (Join-Path $bakDir 'files') $b.rel) $abs $b.sha }
            elseif (Test-Path -LiteralPath $abs) {
                $d = Join-Path (Join-Path $Root '_to_delete') "update_revert_$stamp"; New-Item -ItemType Directory -Path $d -Force | Out-Null
                Move-Item -LiteralPath $abs -Destination (Join-Path $d ($b.rel -replace '[\\/]', '__')) -Force
            }
        }
        Log 'files restored byte-exact from the backup (sha256 verified)'
    } catch { Log "REVERT COPY FAILED: $($_.Exception.Message) - restore $bakDir\files over the root by hand"; exit 3 }
    [IO.File]::WriteAllText((Join-Path $Root 'restart.request'), "update revert`r`n", $Utf8)
    $ok = $null
    for ($round = 0; $round -lt 2 -and -not $ok; $round++) {
        $deadline = (Get-Date).AddSeconds(60)
        while ((Get-Date) -lt $deadline -and -not $ok) {
            $st = Status; $age = AliveAge
            if ($st -and $st.version -eq $script:oldVersion -and $null -ne $age -and $age -lt 10) { $ok = $st }
            Start-Sleep -Milliseconds 500
        }
        if ($ok) { break }
        $procs = Watcher-Procs
        if ($procs.Count) {
            foreach ($p in $procs) { Log "watcher did not come back on the old files in 60 s - stopping powershell $($p.ProcessId) so the launcher restarts it"; Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue }
        } else {
            $cl = "$env:ComSpec /c `"`"$(Join-Path $src 'watch.cmd')`"`""
            $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $cl; CurrentDirectory = $src }
            Log "no watcher process - started the launcher (pid $($r.ProcessId), rc $($r.ReturnValue))"
        }
    }
    if ($ok) { Log "REVERTED: watcher $($ok.version) pid $($ok.pid) is healthy on the old files" } else { Log "REVERT: the old watcher is not healthy after 2 min - Liam double-clicks $src\watch.cmd" }
    exit 1
}

Log "begin (pid $PID): kit $Kit, noop window $NoopS s, healthy window $HealthyS s, stable window $StableS s"
$man = [IO.File]::ReadAllText((Join-Path $Kit 'manifest.json'), $Utf8) | ConvertFrom-Json
if ($man.kind -ne 'harness') { Log "ABORT: $Kit is not a harness kit (kind=$($man.kind)) - nothing changed"; exit 2 }
$expect = [string]$man.watcher_version
$plan = @()
foreach ($e in @($man.files)) {
    $rel = ([string]$e.path) -replace '/', '\'
    if ($rel -match '(^|\\)\.\.(\\|$)' -or [IO.Path]::IsPathRooted($rel) -or -not ($rel -match '^(src|profiles)\\')) { Log "ABORT: kit path '$($e.path)' is outside src\ and profiles\ - nothing changed"; exit 2 }
    $staged = Join-Path $Kit $e.staged
    if (-not (Test-Path -LiteralPath $staged) -or (Sha $staged) -ne $e.sha256) { Log "ABORT: staged file $($e.staged) is missing or does not match the manifest sha256 (stale or partial copy; re-send the kit under a new id) - nothing changed"; exit 2 }
    $plan += [pscustomobject]@{ rel = $rel; staged = $staged; sha = [string]$e.sha256 }
}
# J2 question 4: a manifest copied from another kit (run 20261029T002439Z: kit j2badwatcher carried the good kit's id and files) is refused
$leaf = Split-Path $Kit -Leaf
if ([string]$man.kit_id -ne $leaf) { Log "ABORT: the manifest's kit_id '$($man.kit_id)' is not this kit's folder '$leaf' (a manifest copied from another kit; re-send the kit) - nothing changed"; exit 2 }
# J2 L7: an update with nothing to replace is its own outcome (exit 4): no backup, no restart, never CONFIRMED
$todo = @($plan | Where-Object { $a = Join-Path $Root $_.rel; -not (Test-Path -LiteralPath $a) -or (Sha $a) -ne $_.sha })
if (@($todo | Where-Object { $_.rel -ne 'src\watch.cmd' }).Count -eq 0) {
    if ($todo.Count) { Log 'src\watch.cmd differs in the kit but is never replaced while it runs: re-run Install watcher.cmd for a new launcher' }
    Log "NOTHING TO DO: every file of kit $($man.kit_id) is already in place (sha256) - no backup, no restart"; exit 4
}
$st0 = Status; $age0 = AliveAge
if (-not $st0 -or $null -eq $age0 -or $age0 -gt 10) { Log 'ABORT: the watcher is not running (heartbeat stale) - nothing changed; use Install watcher.cmd'; exit 2 }
$script:oldVersion = $st0.version; $script:oldPid = [int]$st0.pid
Log "live watcher $($script:oldVersion) pid $($script:oldPid); kit $($man.kit_id) carries watcher $expect"
$deadline = (Get-Date).AddSeconds(120)
while ($true) {
    $st = Status
    if ($st -and -not $st.current_job) { break }
    if ((Get-Date) -gt $deadline) { Log 'ABORT: the watcher slot did not become idle within 120 s - nothing changed'; exit 2 }
    Start-Sleep -Milliseconds 500
}
# 1. back up every file the kit touches (sha256 verified), 2. replace, 3. restart, 4. prove it
New-Item -ItemType Directory -Path (Join-Path $bakDir 'files') -Force | Out-Null
$changed = 0
foreach ($p in $plan) {
    $abs = Join-Path $Root $p.rel
    $b = [ordered]@{ rel = $p.rel; existed = $false; sha = $null }
    if (Test-Path -LiteralPath $abs) {
        $dst = Join-Path (Join-Path $bakDir 'files') $p.rel
        New-Item -ItemType Directory -Path (Split-Path $dst) -Force | Out-Null
        Copy-Item -LiteralPath $abs -Destination $dst -Force
        $b.existed = $true; $b.sha = Sha $abs
        if ((Sha $dst) -ne $b.sha) { Log "ABORT: backup copy of $($p.rel) does not verify - nothing changed"; exit 2 }
    }
    $script:Backed += [pscustomobject]$b
}
[IO.File]::WriteAllText((Join-Path $bakDir 'manifest.json'), (([pscustomobject]@{ kit_id = $man.kit_id; created_utc = (Utc); old_version = $script:oldVersion; files = $script:Backed }) | ConvertTo-Json -Depth 4), $Utf8)
Log "backup: $bakDir ($($script:Backed.Count) files)"
try {
    foreach ($p in $plan) {
        $abs = Join-Path $Root $p.rel
        if ((Test-Path -LiteralPath $abs) -and (Sha $abs) -eq $p.sha) { continue }
        if ($p.rel -eq 'src\watch.cmd') { Log 'src\watch.cmd changed in the kit but is never replaced while it runs (cmd re-reads it): re-run Install watcher.cmd for a new launcher'; continue }
        Put $p.staged $abs $p.sha; $changed++
    }
    Log "$changed file(s) replaced"
} catch { Log "copy failed: $($_.Exception.Message)"; Revert 'copy failed' }
[IO.File]::WriteAllText((Join-Path $Root 'restart.request'), "update`r`n", $Utf8)
# healthy: the expected version under a NEW pid, a fresh heartbeat, no zombie. A needs_reboot flag the old watcher already had passes
# (J2 L1: a zombie flag set before the update must not block the update that may fix it); a NEW one still fails the update.
$rebootBefore = [bool]$st0.needs_reboot
$ok = $null; $deadline = (Get-Date).AddSeconds($HealthyS)
while ((Get-Date) -lt $deadline -and -not $ok) {
    $st = Status; $age = AliveAge
    if ($st -and (-not $expect -or $st.version -eq $expect) -and [int]$st.pid -ne $script:oldPid -and $null -ne $age -and $age -lt 10 -and ($rebootBefore -or -not $st.needs_reboot)) { $ok = $st }
    Start-Sleep -Milliseconds 500
}
if (-not $ok) { Revert "watcher $expect not healthy within $HealthyS s" }
Log "watcher $($ok.version) pid $($ok.pid) is up; sending a noop job (must answer within $NoopS s)"
# the dead-man switch: the NEW watcher must pick up and answer a job
$nid = Submit-Noop
$done = Join-Path (Join-Path $Root 'jobs') "$nid.done"
$deadline = (Get-Date).AddSeconds($NoopS); $ans = $null
while ((Get-Date) -lt $deadline -and -not $ans) {
    if (Test-Path -LiteralPath $done) { try { $ans = [IO.File]::ReadAllText($done, $Utf8) | ConvertFrom-Json } catch { } }
    Start-Sleep -Milliseconds 300
}
if (-not $ans) { Revert "the new watcher did not answer a noop job within $NoopS s" }
if ($ans.status -ne 'ok' -or ($expect -and $ans.watcher -ne $expect)) { Revert "the noop answer was status=$($ans.status) watcher=$($ans.watcher)" }
Log "noop answered by watcher $($ans.watcher): ok; watching the heartbeat for $StableS s"
$deadline = (Get-Date).AddSeconds($StableS)
while ((Get-Date) -lt $deadline) {
    $age = AliveAge
    if ($null -eq $age -or $age -gt 30) { Revert "the watcher stopped during the stable window (heartbeat $(if ($null -eq $age) { 'missing' } else { [int]$age }) s old)" }
    Start-Sleep -Seconds 1
}
Log "CONFIRMED: watcher $($ok.version) stays; rollback copy in $bakDir"
exit 0
