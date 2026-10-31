# purpose: static and unit host tests for the harness: every learning from the earlier remaster's watcher history as a guard (BOM-less UTF-8, byte[] returns, UTC everywhere, id and lock rules, hang verdicts, overlays, profile snapshot/restore, tolerant status reads)
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File Test-Unit.ps1 [-Repo <repo root>]   (CI: Windows PowerShell 5.1; the pure parts also run under pwsh on Linux)
# when: on every push (CI job harness-windows) and before committing a change to harness/
# not-a-verb: a PowerShell test script, not a repo operation
param([string]$Repo = '')
$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'Test-Lib.ps1')
if (-not $Repo) { $Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
# the harness scripts: harness\core\ before the move to warscape-core, harness\ after it (J12); the tests find them, not a layout
$core = Split-Path $PSScriptRoot; if (Test-Path -LiteralPath (Join-Path $core 'core\watcher.ps1')) { $core = Join-Path $core 'core' }
$allScripts = @(Get-ChildItem -LiteralPath (Split-Path $PSScriptRoot) -Recurse -File | Where-Object { $_.Extension -in '.ps1', '.cmd' })
$coreScripts = @($allScripts | Where-Object { $_.DirectoryName -eq [IO.Path]::GetFullPath($core) })

# ---- static guards over the source ---------------------------------------------------------------------------------------------
Test-Case 'static: every harness script parses (Windows PowerShell grammar)' {
    foreach ($f in $allScripts | Where-Object { $_.Extension -eq '.ps1' }) {
        $e = $null; $t = $null
        [void][Management.Automation.Language.Parser]::ParseFile($f.FullName, [ref]$t, [ref]$e)
        if ($e.Count) { throw "$($f.Name): line $($e[0].Extent.StartLineNumber): $($e[0].Message)" }
    }
}
Test-Case 'static: scripts are pure ASCII with no BOM (5.1 reads a BOM-less script as ANSI)' {
    foreach ($f in $allScripts) {
        $b = [IO.File]::ReadAllBytes($f.FullName)
        if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { throw "$($f.Name) has a BOM" }
        for ($i = 0; $i -lt $b.Length; $i++) { if ($b[$i] -gt 127) { throw "$($f.Name): non-ASCII byte at offset $i" } }
    }
}
Test-Case 'static: batch files have CRLF line ends (an LF-only .cmd can break goto and labels)' {
    if (-not $env:CI) { Write-Host '      (skipped locally: a Linux working copy is LF until git checks it out; CI checks it)'; return }
    foreach ($f in $allScripts | Where-Object { $_.Extension -eq '.cmd' }) {
        $t = [IO.File]::ReadAllText($f.FullName)
        if ($t -match '(?<!\r)\n') { throw "$($f.Name) has a bare LF" }
    }
}
Test-Case 'static: nothing in harness/core can write UTF-16 or a BOM, or format time in local culture' {
    $ban = @(
        @{ rx = 'Tee-Object'; why = 'Tee-Object writes UTF-16 in 5.1' }, @{ rx = '\*>'; why = '*> redirection writes UTF-16 in 5.1' },
        @{ rx = 'Out-File'; why = 'Out-File defaults to UTF-16' }, @{ rx = 'Set-Content|Add-Content'; why = 'ANSI default in 5.1; use [IO.File] with $Utf8' },
        @{ rx = '\[Text\.Encoding\]::UTF8\b'; why = 'the UTF8 property writes a BOM; use New-Object Text.UTF8Encoding $false' },
        @{ rx = '-Encoding\s+(UTF8|Unicode)'; why = 'BOM or UTF-16' }, @{ rx = 'schtasks'; why = 'schtasks /create is refused without elevation; use Register-ScheduledTask' },
        @{ rx = 'return\s+\$\w+\.ToArray\(\)'; why = 'return ,$x.ToArray(): PowerShell unrolls a bare byte[]' },
        @{ rx = 'ToLocalTime|Get-Date\s+-(UFormat|Format)'; why = 'timestamps are UTC everywhere' },
        @{ rx = "ToString\('[^']*[Hh]:[^']*'\)"; why = 'a time format with a colon needs the invariant culture argument' }
    )
    foreach ($f in $coreScripts | Where-Object { $_.Extension -eq '.ps1' }) {
        $n = 0
        foreach ($line in [IO.File]::ReadAllLines($f.FullName)) {
            $n++
            if ($line.TrimStart().StartsWith('#')) { continue }
            foreach ($b in $ban) { if ($line -match $b.rx) { throw "$($f.Name):$n matches /$($b.rx)/ : $($b.why)" } }
        }
    }
}
Test-Case 'static: the display tool changes a display only through Cds-Test (CDS_TEST) and Cds-Apply (dynamic, selection-checked), never persists or touches topology' {
    $t = [IO.File]::ReadAllLines((Join-Path $core 'vdisplay_probe.ps1'))
    $calls = @($t | Where-Object { $_ -match '\[VProbe\]::ChangeDisplaySettingsEx\(' })
    Assert-Eq $calls.Count 2 'exactly two ChangeDisplaySettingsEx call sites'
    $test = @($calls | Where-Object { $_ -match 'function Cds-Test' }); $apply = @($calls | Where-Object { $_ -match 'function Cds-Apply' })
    Assert-Eq $test.Count 1 'one is Cds-Test'; Assert-Match $test[0] 'CDS_TEST' 'Cds-Test passes CDS_TEST'
    Assert-Eq $apply.Count 1 'the other is Cds-Apply'; Assert-Match $apply[0] 'Assert-Selected' 'Cds-Apply re-checks the selection'
    Assert-Match $apply[0] 'ChangeDisplaySettingsEx\(\$sel\.display\.Device, \[ref\]\$dm, \[IntPtr\]::Zero, 0, ' 'Cds-Apply is dynamic (flags 0)'
    Assert-Match $apply[0] '\$sel\.display\.Device' 'and acts on the selected display'
    $joined = ($t | Where-Object { -not $_.TrimStart().StartsWith('#') }) -join "`n"
    Assert-NotMatch $joined 'CDS_UPDATEREGISTRY|SetDisplayConfig|CDS_NORESET|CDS_FULLSCREEN|CDS_SET_PRIMARY' 'no persist flag, no primary change, no topology API'
    Assert-Eq ([regex]::Matches($joined, 'Cds-Apply ').Count) 1 'Cds-Apply is called from one place (Apply-ToVirtual)'
    $pe = $null; $pt = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $core 'vdisplay_probe.ps1'), [ref]$pt, [ref]$pe)
    $fn = $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Apply-ToVirtual' }, $true)
    Assert-Match $fn.Body.Extent.Text 'Cds-Apply \$sel' 'Apply-ToVirtual hands Cds-Apply the selection, not a device string'
}
Test-Case 'static: update.ps1 judges liveness from the heartbeat file mtime and retries status reads' {
    $t = [IO.File]::ReadAllText((Join-Path $core 'update.ps1'))
    Assert-Match $t 'watcher\.alive' 'uses watcher.alive'
    Assert-Match $t 'LastWriteTime' 'uses its mtime'
    Assert-Match $t 'for \(\$i = 0; \$i -lt 8; \$i\+\+\)' 'retries the status read'
}

# ---- unit tests on the watcher's functions (dot-sourced, no main loop) ----------------------------------------------------------
$tmp = New-Tmp 'unit'
$root = Join-Path $tmp 'watcher'; New-Item -ItemType Directory -Path $root -Force | Out-Null
$adapterPath = New-TestAdapter $tmp
. (Join-Path $core 'watcher.ps1') -Root $root -Adapter $adapterPath -NoRun
Ensure-Dirs

Test-Case 'Read-Shared always returns a byte[] (0, 1 and N bytes): an empty file must not become $null' {
    foreach ($n in 0, 1, 7, 5000) {
        $p = Join-Path $tmp "rs$n.bin"; [IO.File]::WriteAllBytes($p, [byte[]](1..255 * 40)[0..($n - 1)] + $(if ($n -eq 0) { [byte[]]@() } else { [byte[]]@() }))
        if ($n -eq 0) { [IO.File]::WriteAllBytes($p, [byte[]]@()) }
        $b = Read-Shared $p
        Assert-True ($null -ne $b) "n=$n not null"
        Assert-Eq $b.GetType().FullName 'System.Byte[]' "n=$n type"
        Assert-Eq $b.Length ([IO.FileInfo]$p).Length "n=$n length"
    }
}
Test-Case 'UtcStr is UTC, labelled Z and culture-proof' {
    $d = New-Object DateTime 2026, 10, 28, 12, 34, 56, ([DateTimeKind]::Utc)
    Assert-Eq (UtcStr $d) '2026-10-28T12:34:56Z' 'utc in'
    Assert-Eq (UtcStr $d.ToLocalTime()) '2026-10-28T12:34:56Z' 'local in, utc out'
    Assert-Eq (UtcStamp $d) '20261028T123456Z' 'stamp'
    $old = [Threading.Thread]::CurrentThread.CurrentCulture
    try {
        foreach ($c in 'fi-FI', 'ar-SA', 'th-TH') {
            try { [Threading.Thread]::CurrentThread.CurrentCulture = New-Object Globalization.CultureInfo $c } catch { continue }
            Assert-Eq (UtcStr $d) '2026-10-28T12:34:56Z' "culture $c"
        }
    } finally { [Threading.Thread]::CurrentThread.CurrentCulture = $old }
}
Test-Case 'Parse-KV reads owner, session, a purpose with spaces, started and hang_s' {
    $kv = Parse-KV 'owner=agent-1 session=s9 purpose=load a big battle started=2026-10-28T10:00:00Z hang_s=30'
    Assert-Eq $kv['owner'] 'agent-1' 'owner'; Assert-Eq $kv['purpose'] 'load a big battle' 'purpose'; Assert-Eq $kv['hang_s'] '30' 'hang_s'
    Assert-Eq $kv['started'] '2026-10-28T10:00:00Z' 'started'
}
Test-Case 'job ids: pattern enforced' {
    foreach ($ok in 'a', 'agent-20261028T100000Z-123', 'x.y_z-1') { Assert-True (Is-ValidId $ok) $ok }
    foreach ($bad in '', '-x', '.x', 'a b', 'a/b', 'a..\b', ('x' * 121)) { Assert-True (-not (Is-ValidId $bad)) "bad id [$bad]" }
}
Test-Case 'game lock: absent, empty, owner rules, refresh by mtime, staleness after 20 minutes' {
    $lock = Join-Path $root 'game.lock'
    Assert-True ($null -eq (Get-Lock)) 'no lock'
    Assert-Match (Check-Owner 'a') 'no game.lock' 'refused without a lock'
    [IO.File]::WriteAllBytes($lock, [byte[]]@())
    Assert-True ($null -eq (Get-Lock)) '0 bytes counts as absent (being written)'
    [IO.File]::WriteAllText($lock, "owner=alice session=s1 purpose=a test started=2026-10-28T10:00:00Z hang_s=45`r`n", $Utf8)
    $l = Get-Lock
    Assert-Eq $l.owner 'alice' 'owner'; Assert-Eq $l.hang_s '45' 'hang_s'; Assert-True (-not $l.stale) 'fresh'
    Assert-True ($null -eq (Check-Owner 'alice')) 'owner accepted'
    Assert-Match (Check-Owner 'bob') "owner=bob does not hold the game" 'wrong owner'
    Assert-Match (Check-Owner '') 'carries no owner' 'missing owner'
    (Get-Item -LiteralPath $lock).LastWriteTime = (Get-Date).AddMinutes(-19)
    Assert-True (-not (Get-Lock).stale) '19 min is not stale'
    (Get-Item -LiteralPath $lock).LastWriteTime = (Get-Date).AddMinutes(-21)
    Assert-True ((Get-Lock).stale) '21 min is stale'
    Assert-Match (Check-Owner 'alice') 'stale' 'a stale lock is no lock'
    Expire-StaleLock
    Assert-True (-not (Test-Path -LiteralPath $lock)) 'expired lock moved away'
    Assert-Eq @(Get-ChildItem (Join-Path $root '_to_delete') -Filter 'game.lock.expired_alice_*').Count 1 'moved to _to_delete'
    $log = [IO.File]::ReadAllText($LogPath)
    Assert-Match $log 'LOCK EXPIRED: game.lock owner=alice' 'logged'
    Assert-Match $log '^\[\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\] ' 'log lines start with a UTC timestamp'
}
Test-Case 'foreign lock (another watcher on this PC) is read, never written' {
    $fl = $A.foreign_locks[0]; New-Item -ItemType Directory -Path (Split-Path $fl) -Force | Out-Null
    Assert-True ($null -eq (Foreign-LockReason)) 'none'
    [IO.File]::WriteAllText($fl, "owner=other-agent session=e purpose=probe started=2026-10-28T10:00:00Z`r`n", $Utf8)
    Assert-Match (Foreign-LockReason) 'another watcher.*other-agent' 'fresh foreign lock blocks'
    $before = Sha256File $fl
    (Get-Item -LiteralPath $fl).LastWriteTime = (Get-Date).AddMinutes(-30)
    Assert-True ($null -eq (Foreign-LockReason)) 'a stale foreign lock does not block'
    Remove-Item -LiteralPath $fl -Force
}
Test-Case 'hang verdict: CPU idle AND log quiet for hang_s; start-up grace; minimised is not a hang; IsHungAppWindow counts only when sustained' {
    $base = @{ armed = $true; off = $false; since_start_s = 500; window = 'visible'; window_hung_s = 0; cpu_idle_s = 0; log_idle_s = 0; hang_s = 120; startup_s = 180; hung_window_s = 60; holds_game = $false }
    function V($over) { $f = $base.Clone(); foreach ($k in $over.Keys) { $f[$k] = $over[$k] }; return (Get-HangVerdict $f).hung }
    Assert-True (-not (V @{})) 'alive'
    Assert-True (V @{ cpu_idle_s = 130; log_idle_s = 130 }) 'idle cpu and quiet log = hung'
    Assert-True (-not (V @{ cpu_idle_s = 130; log_idle_s = 5 })) 'log still written = alive'
    Assert-True (-not (V @{ cpu_idle_s = 5; log_idle_s = 130 })) 'cpu still moving = alive'
    Assert-True (V @{ cpu_idle_s = 130; log_idle_s = $null }) 'no heartbeat file configured: CPU alone decides'
    Assert-True (-not (V @{ cpu_idle_s = 130; log_idle_s = 130; since_start_s = 100 })) 'start-up grace'
    Assert-True (-not (V @{ cpu_idle_s = 130; log_idle_s = 130; window = 'minimized' })) 'minimised window is not a hang'
    Assert-True (-not (V @{ cpu_idle_s = 130; log_idle_s = 130; window = 'hidden' })) 'hidden window is not a hang'
    Assert-True (-not (V @{ cpu_idle_s = 130; log_idle_s = 130; armed = $false })) 'not armed: a game Liam started himself is never touched'
    Assert-True (-not (V @{ cpu_idle_s = 130; log_idle_s = 130; off = $true })) 'watchdog off'
    Assert-True (-not (V @{ cpu_idle_s = 130; log_idle_s = 130; holds_game = $true })) 'a launch/kill job is handling the game'
    Assert-True (V @{ window = 'not_responding'; window_hung_s = 61 }) 'IsHungAppWindow sustained = hung'
    Assert-True (-not (V @{ window = 'not_responding'; window_hung_s = 10 })) 'a short freeze while loading is not a hang'
}
Test-Case 'Write-Atomic + Read-JsonRetry: a status file replaced every few ms is never read as broken' {
    $p = Join-Path $tmp 'busy.status'
    Write-Atomic $p '{"n":0}'
    $rs = [runspacefactory]::CreateRunspace(); $rs.Open()
    $ps = [powershell]::Create(); $ps.Runspace = $rs
    [void]$ps.AddScript({
        param($path, $count)
        $enc = New-Object Text.UTF8Encoding $false
        for ($i = 1; $i -le $count; $i++) {
            $tmpf = "$path.wtmp"; [IO.File]::WriteAllText($tmpf, ('{"n":' + $i + ',"pad":"' + ('x' * 3000) + '"}'), $enc)
            for ($k = 0; $k -lt 20; $k++) { try { [IO.File]::Replace($tmpf, $path, [NullString]::Value); break } catch { Start-Sleep -Milliseconds 5 } }
        }
    }).AddArgument($p).AddArgument(3000)
    $h = $ps.BeginInvoke()
    $bad = 0; $reads = 0
    while (-not $h.IsCompleted) { $j = Read-JsonRetry $p; $reads++; if ($null -eq $j) { $bad++ } }
    $ps.EndInvoke($h); $ps.Dispose(); $rs.Dispose()
    Assert-True ($reads -gt 3) "read $reads times"
    Assert-Eq $bad 0 'unreadable results'
}
Test-Case 'Get-AliveAgeS: liveness is the heartbeat file mtime' {
    $d = Join-Path $tmp 'alive'; New-Item -ItemType Directory -Path $d -Force | Out-Null
    Assert-True ($null -eq (Get-AliveAgeS $d)) 'no file: unknown'
    [IO.File]::WriteAllText((Join-Path $d 'watcher.alive'), 'x')
    Assert-True ((Get-AliveAgeS $d) -lt 5) 'fresh'
    (Get-Item -LiteralPath (Join-Path $d 'watcher.alive')).LastWriteTime = (Get-Date).AddSeconds(-60)
    Assert-True ((Get-AliveAgeS $d) -gt 55) 'old'
}

function Enc([string]$s) { return $Latin1.GetBytes($s) }
function Dec([byte[]]$b) { return $Latin1.GetString($b) }
Test-Case 'overlay (ini): replaces a key, keeps CRLF and every other byte, adds a key at the end of its section, creates a section' {
    $base = "; head`r`n[proxy]`r`nbackend=system`r`nlog_level=info`r`n`r`n[other]`r`nx=1`r`n"
    Assert-Eq (Dec (Apply-Overlay (Enc $base) "proxy.backend=dxvk`n" 'ini' 't')) ($base.Replace('backend=system', 'backend=dxvk')) 'replace'
    Assert-Eq (Dec (Apply-Overlay (Enc $base) "proxy.backend=system`n" 'ini' 't')) $base 'same value = identical bytes'
    $r = Dec (Apply-Overlay (Enc $base) "proxy.minidump=2`n" 'ini' 't')
    Assert-Eq $r "; head`r`n[proxy]`r`nbackend=system`r`nlog_level=info`r`nminidump=2`r`n`r`n[other]`r`nx=1`r`n" 'added at the end of [proxy], before the blank line and [other]'
    $r = Dec (Apply-Overlay (Enc $base) "extra.k=v`n" 'ini' 't')
    Assert-Eq $r ($base + "`r`n[extra]`r`nk=v`r`n") 'new section at the end'
    $r = Dec (Apply-Overlay (Enc $base) "!proxy.log_level`n" 'ini' 'p1')
    Assert-Match $r '; \(profile p1\) log_level=info' 'removed key commented out'
}
Test-Case 'overlay (ini): LF files stay LF, duplicates are commented, an empty or absent base works' {
    $r = Dec (Apply-Overlay (Enc "[proxy]`nbackend=a`nbackend=b`n") "proxy.backend=dxvk`n" 'ini' 'p')
    Assert-Eq $r "[proxy]`nbackend=dxvk`n; (profile p) backend=b`n" 'dups'
    Assert-Eq (Dec (Apply-Overlay ([byte[]]@()) "proxy.backend=dxvk`n" 'ini' 'p')) "[proxy]`r`nbackend=dxvk`r`n" 'absent base'
}
Test-Case 'overlay: UTF-16LE with BOM survives (the encoding and BOM are kept)' {
    $u16 = New-Object Text.UnicodeEncoding($false, $false)
    $base = [byte[]]@(0xFF, 0xFE) + $u16.GetBytes("[proxy]`r`nbackend=system`r`n")
    $out = Apply-Overlay $base "proxy.backend=dxvk`n" 'ini' 'p'
    Assert-True ($out[0] -eq 0xFF -and $out[1] -eq 0xFE) 'BOM kept'
    Assert-Eq $u16.GetString($out, 2, $out.Length - 2) "[proxy]`r`nbackend=dxvk`r`n" 'content'
}
Test-Case 'overlay (conf): whole-name keys, written as "key = value", appended when missing; style none refuses' {
    $r = Dec (Apply-Overlay (Enc "# dxvk`nd3d9.maxFrameRate = 0`n") "d3d9.maxFrameRate = 60`ndxvk.logLevel = info`n" 'conf' 'p')
    Assert-Eq $r "# dxvk`nd3d9.maxFrameRate = 60`ndxvk.logLevel = info`n" 'conf'
    $threw = $false; try { Apply-Overlay (Enc 'x') "a=b`n" 'none' 'p' } catch { $threw = $true }
    Assert-True $threw 'style none throws (only a full copy is allowed)'
}

# ---- profiles: snapshot, apply, switch (never stack), restore byte for byte, absent as a recorded state ---------------------------
$profSrc = Join-Path $PSScriptRoot 'fixtures\profiles'
Copy-Item -Path (Join-Path $profSrc '*') -Destination $ProfilesDir -Recurse -Force
$prefs = Join-Path $A.appdata_dir 'scripts\preferences.script.txt'
$keys = Join-Path $A.appdata_dir 'custom_keys.keys.xml'
$ini = Join-Path $A.game_dir 'testmod.ini'
$dxc = Join-Path $A.game_dir 'dxvk.conf'
$odd = [byte[]](0, 255, 13, 10, 10, 13, 0xC3, 0xA9, 200, 1, 2, 3)           # NULs, lone CR/LF, high bytes: nothing may normalise these
[IO.File]::WriteAllBytes($prefs, $odd)
[IO.File]::WriteAllBytes($keys, (Enc "<keys/>"))
function Hashes { return ((@($prefs, $keys, $ini, $dxc) | ForEach-Object { if (Test-Path -LiteralPath $_) { Sha256File $_ } else { 'absent' } }) -join ',') }
$baseline = Hashes
Test-Case 'profile: apply proxy-dxvk with the mod files absent, restore returns every file to its baseline (absent stays absent)' {
    $o = New-Object Collections.Generic.List[string]
    $err = Profile-Apply 'proxy-dxvk' 'agent1' $o
    Assert-True ($null -eq $err) "apply: $err"
    Assert-True (Test-Path -LiteralPath $ini) 'ini installed from absent'
    Assert-Match (Dec ([IO.File]::ReadAllBytes($ini))) '(?m)^backend=dxvk' 'overlay applied to an empty base'
    Assert-Match (Dec ([IO.File]::ReadAllBytes($dxc))) 'dxvk\.logLevel = info' 'dxvk.conf installed'
    Assert-True (($o -join "`n") -match 'WARNING: game:d3d9.dll is not on the PC') 'warns that the DLL is not installed'
    $act = Get-Active; Assert-Eq $act.owner 'agent1' 'active owner'
    $o2 = New-Object Collections.Generic.List[string]
    $err = Profile-Restore 'test' $o2
    Assert-True ($null -eq $err) "restore: $err"
    Assert-Eq (Hashes) $baseline 'byte for byte'
    Assert-True (-not (Test-Path -LiteralPath $ini)) 'absent again'
    Assert-True ($null -eq (Get-Active)) 'no active profile'
    Assert-True (@(Get-ChildItem (Join-Path $root '_to_delete') -Recurse -Filter 'mod_ini__*').Count -ge 1) 'the file moved to _to_delete, not deleted'
}
Test-Case 'profile: files that exist are overlaid, switching A to B never stacks, restore returns to the first snapshot' {
    [IO.File]::WriteAllBytes($ini, (Enc "[proxy]`r`nbackend=system`r`nlog_level=debug`r`n"))
    [IO.File]::WriteAllBytes($dxc, (Enc "d3d9.maxFrameRate = 0`r`n"))
    $b2 = Hashes
    $o = New-Object Collections.Generic.List[string]
    Assert-True ($null -eq (Profile-Apply 'proxy-dxvk' 'agent1' $o)) 'apply A'
    Assert-Eq (Dec ([IO.File]::ReadAllBytes($ini))) "[proxy]`r`nbackend=dxvk`r`nlog_level=debug`r`n" 'ini overlay keeps the other key and CRLF'
    $snap = (Get-Active).snapshot
    Assert-True ($null -eq (Profile-Apply 'vanilla' 'agent1' $o)) 'switch to B'
    Assert-True (-not (Test-Path -LiteralPath $ini)) 'B made the ini absent, nothing of A is left'
    Assert-Eq (Get-Active).snapshot $snap 'the first snapshot is kept'
    Assert-True ($null -eq (Profile-Apply 'proxy-dxvk' 'agent1' $o)) 'back to A'
    Assert-Eq (Dec ([IO.File]::ReadAllBytes($ini))) "[proxy]`r`nbackend=dxvk`r`nlog_level=debug`r`n" 'A applied on the snapshot base, not on top of B'
    Assert-True ($null -eq (Profile-Restore 'test' $o)) 'restore'
    Assert-Eq (Hashes) $b2 'byte for byte'
}
Test-Case 'profile: another owner is refused while one is active; unknown profile and bad names are refused with the reason' {
    $o = New-Object Collections.Generic.List[string]
    Assert-True ($null -eq (Profile-Apply 'vanilla' 'agent1' $o)) 'apply'
    Assert-Match (Profile-Apply 'proxy-dxvk' 'agent2' $o) "still active" 'other owner'
    Assert-Match (Profile-Apply 'nope' 'agent1' $o) "no profile 'nope' \(have: " 'unknown'
    Assert-Match (Profile-Apply '..\x' 'agent1' $o) 'bad profile name' 'bad name'
    Assert-True ($null -eq (Profile-Restore 'test' $o)) 'restore'
}
Test-Case 'profile: an overlay on a style-none target (keys) is refused before anything is written' {
    $d = Join-Path $ProfilesDir 'badprefs'; New-Item -ItemType Directory -Path $d -Force | Out-Null
    [IO.File]::WriteAllText((Join-Path $d 'keys.set'), "x=1`n")
    $h = Hashes; $o = New-Object Collections.Generic.List[string]
    Assert-Match (Profile-Apply 'badprefs' 'agent1' $o) "only a full copy" 'refused'
    Assert-Eq (Hashes) $h 'nothing touched'
    Assert-True ($null -eq (Get-Active)) 'nothing active'
    Remove-Item -LiteralPath $d -Recurse -Force
}
Test-Case 'profile: a mismatching restore is reported, not hidden' {
    $baseline = Hashes
    $o = New-Object Collections.Generic.List[string]
    Assert-True ($null -eq (Profile-Apply 'vanilla' 'agent1' $o)) 'apply'
    $snapDir = Join-Path $SavedDir (Get-Active).snapshot
    $saved = Join-Path $snapDir 'files\prefs'
    [IO.File]::WriteAllBytes($saved, (Enc 'tampered'))                 # the saved copy no longer matches its sha256
    [IO.File]::WriteAllBytes($prefs, (Enc 'changed by the game'))
    $err = Profile-Restore 'test' $o
    Assert-Match $err 'did not verify' 'restore fails loudly'
    Assert-True ($null -ne (Get-Active)) 'stays active so it is retried'
    [IO.File]::WriteAllBytes($saved, $odd)                              # repair the saved copy and retry
    Assert-True ($null -eq (Profile-Restore 'test' $o)) 'second restore'
    Assert-Eq (Hashes) $baseline 'back to the baseline'
}
Test-Case 'guards: a script that runs git is refused whatever the owner (J18: never git in a game folder); look-alikes pass' {
    foreach ($b in @('git status', 'cd /d "C:\g" && git init', '"C:\Program Files\Git\bin\git.exe" log', '& git -C C:\g status', 'GIT.EXE fetch')) {
        Assert-True ($null -ne (Script-RunsGit $b)) "runs git: $b"
    }
    foreach ($b in @('rem git status', ':: git', '# git status', 'dir C:\g\.git', 'echo github', 'type .gitattributes', 'tasklist')) {
        Assert-True ($null -eq (Script-RunsGit $b)) "no git: $b"
    }
}
Test-Case 'exe check: the sha1 against exe_identity.json beside the adapter; a mismatch refuses, warn launches with a warning, no identity is not a pass (J18)' {
    $exe = Join-Path $A.game_dir $A.game_image
    [IO.File]::WriteAllBytes($exe, [Text.Encoding]::ASCII.GetBytes('MZ fake vanilla exe'))
    $good = (Get-FileHash -LiteralPath $exe -Algorithm SHA1).Hash.ToLower()
    $idp = Exe-IdentityPath
    Assert-Eq (Split-Path -Parent $idp) (Split-Path -Parent $adapterPath) 'the copy sits beside adapter.json'
    Remove-Quiet $idp
    $o = New-Object Collections.Generic.List[string]
    Assert-Match (Exe-Gate $o) '^EXE CHECK: no exe identity' 'no identity: refused'
    [IO.File]::WriteAllText($idp, "{`"sha1`": `"$($good.ToUpper())`"}", $Utf8)
    Assert-True ($null -eq (Exe-Gate $o)) 'vanilla: launch goes ahead'
    Assert-Match ($o -join ' ') 'exe check: ok' 'and says so'
    Assert-Eq $ExeState.ok $true 'state ok'; Assert-Eq $ExeState.sha1 $good 'state sha1'
    [IO.File]::WriteAllText($idp, '{"sha1": "0000000000000000000000000000000000000000"}', $Utf8)
    $r = Exe-Gate $o
    Assert-Match $r '^EXE CHECK: MISMATCH' 'mismatch: refused'
    Assert-Match $r 'exe_info\.py' 'names the next step'
    Assert-NotMatch $r 'did not verify|^ZOMBIE|watcher error' 'a refusal (exit -2), not a failure'
    $S.exe_check = 'warn'
    try { $o2 = New-Object Collections.Generic.List[string]; Assert-True ($null -eq (Exe-Gate $o2)) 'warn: goes ahead'; Assert-Match ($o2 -join ' ') 'WARNING \(watcher\): exe check failed' 'with a warning' }
    finally { $S.exe_check = 'refuse' }
    $old = $ExeCache.key
    [IO.File]::WriteAllBytes($exe, [Text.Encoding]::ASCII.GetBytes('MZ fake patched exe, longer'))
    [void](Exe-Check)
    Assert-True ($ExeCache.key -ne $old) 'a changed exe is hashed again (size + mtime cache)'
    Remove-Quiet $idp; Remove-Quiet $exe
}
Test-Case 'guards: scripts that start/kill the game or write its config need an owner; read-only ones never do' {
    Assert-True ($null -ne (Script-TouchesGame 'taskkill /f /im Game.exe')) 'taskkill'
    Assert-True ($null -ne (Script-TouchesGame 'start "" "C:\x\Game.exe"')) 'start'
    Assert-True ($null -ne (Script-TouchesGame 'Stop-Process -Name Game -Force')) 'Stop-Process'
    Assert-True ($null -ne (Script-TouchesGame 'start steam://rungameid/34030')) 'steam'
    Assert-True ($null -ne (Script-TouchesGame '& "C:\x\Other.exe"')) 'direct call (either title)'
    Assert-True ($null -eq (Script-TouchesGame 'tasklist /fi "imagename eq Game.exe" /fo csv /nh')) 'tasklist is read-only'
    Assert-True ($null -eq (Script-TouchesGame 'rem taskkill /f /im Game.exe')) 'comments are ignored'
    Assert-True ($null -ne (Script-TouchesConfig 'copy x.txt "C:\g\dxvk.conf"')) 'copy over a config'
    Assert-True ($null -ne (Script-TouchesConfig 'echo a>> testmod.ini')) 'redirect into a config'
    Assert-True ($null -eq (Script-TouchesConfig 'type dxvk.conf')) 'reading a config is fine'
}
Test-Case 'zombie: cleared when the pid is free or reused by another image (the flag outlives the reboot it asks for)' {
    $z = [pscustomobject]@{ pid = 4242; image = 'Game.exe' }
    Assert-True (Zombie-Gone $z $null) 'pid free'
    Assert-True (Zombie-Gone $z ([pscustomobject]@{ ProcessName = 'svchost' })) 'pid reused by another image'
    Assert-True (-not (Zombie-Gone $z ([pscustomobject]@{ ProcessName = 'Game' }))) 'same image still there'
    Assert-True (-not (Zombie-Gone $z ([pscustomobject]@{ ProcessName = 'GAME' }))) 'image compared case-insensitively'
}
Test-Case 'test runner: -Only selects by regex, -Repeat runs n times and stops at the first failure (J19)' {
    $box = @{ n = 0 }
    $count = { $box.n++ }
    $sel = Invoke-Selected 'hang watchdog: a suspended game' $count 'other case' 5
    Assert-True (-not $sel.ran) 'a case the filter does not match is not run'; Assert-Eq $box.n 0 'body not called'
    $sel = Invoke-Selected 'hang watchdog: a suspended game' $count '^hang watchdog' 5
    Assert-True $sel.ran 'a matching case runs'; Assert-Eq $sel.passed 5 'all 5 runs pass'; Assert-Eq $box.n 5 'body called 5 times'; Assert-True ($null -eq $sel.error) 'no error'
    $box.n = 0
    $sel = Invoke-Selected 'any' $count '' 1
    Assert-True $sel.ran 'no filter: every case runs'; Assert-Eq $box.n 1 'default: once'
    $box.n = 0
    $flaky = { $box.n++; if ($box.n -eq 3) { throw 'third run fails' } }
    $sel = Invoke-Selected 'flaky' $flaky '' 10
    Assert-Eq $sel.passed 2 'two runs passed'; Assert-Eq $box.n 3 'stopped at the first failure'; Assert-Match $sel.error 'third run fails' 'the failure message is kept'
    $box.n = 0
    $sel = Invoke-Selected 'zero' $count '' 0
    Assert-Eq $box.n 1 'a repeat below 1 still runs once'
    foreach ($s in 'Run-HostTests.ps1', 'Test-Integration.ps1') {
        $e = $null; $t = $null
        $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $s), [ref]$t, [ref]$e)
        $ps = @{}; foreach ($p in $ast.ParamBlock.Parameters) { $ps[$p.Name.VariablePath.UserPath] = $p }
        Assert-True ($ps.ContainsKey('Only') -and $ps.ContainsKey('Repeat')) "$s declares -Only and -Repeat"
        Assert-Eq $ps['Only'].DefaultValue.Value '' "$s -Only defaults to no filter"
        Assert-Eq $ps['Repeat'].DefaultValue.Value 1 "$s -Repeat defaults to 1"
        Assert-True (@($ps['Repeat'].Attributes | Where-Object { $_.TypeName.Name -eq 'ValidateRange' }).Count -eq 1) "$s -Repeat is range-checked"
    }
}
Test-Case 'test runner: Test-Lib never assigns a script variable named like a suite parameter (it would reset -Only; J19 run 40898907246)' {
    # params live in the suite's script scope and names are case-insensitive: Test-Lib's `$script:Only = ''` silently reset -Only
    $e = $null; $t = $null
    $lib = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Test-Lib.ps1'), [ref]$t, [ref]$e)
    $assigned = @($lib.FindAll({ param($n) $n -is [Management.Automation.Language.AssignmentStatementAst] -and $n.Left -is [Management.Automation.Language.VariableExpressionAst] }, $true) |
        ForEach-Object { $_.Left.VariablePath.UserPath -replace '^script:', '' })
    foreach ($s in 'Run-HostTests.ps1', 'Test-Integration.ps1', 'Test-Unit.ps1') {
        $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot $s), [ref]$t, [ref]$e)
        foreach ($p in $ast.ParamBlock.Parameters) {
            $pn = $p.Name.VariablePath.UserPath
            Assert-True (-not ($assigned | Where-Object { $_ -ieq $pn })) "Test-Lib.ps1 assigns `$script:$pn, which is the -$pn parameter of $s"
        }
    }
    # and end to end: a suite script with -Only/-Repeat that dot-sources Test-Lib still sees the values
    $probe = Join-Path $tmp 'probe_suite.ps1'
    [IO.File]::WriteAllText($probe, "param([string]`$Only = '', [int]`$Repeat = 1)`r`n. '$(Join-Path $PSScriptRoot 'Test-Lib.ps1')'`r`n`$script:TcOnly = `$Only; `$script:TcRepeat = `$Repeat`r`nWrite-Output `"[`$(`$script:TcOnly)] [`$(`$script:TcRepeat)]`"`r`n", $Utf8NoBom)
    $o = & (Get-Process -Id $PID).Path -NoProfile -ExecutionPolicy Bypass -File $probe -Only 'hang watchdog' -Repeat 3
    Assert-Eq "$o".Trim() '[hang watchdog] [3]' 'the values reach Test-Case through a dot-sourced Test-Lib'
}
Test-Case 'static: the watcher writes its first heartbeat before its first housekeeping pass (a slow pass is not a dead watcher; J42)' {
    $text = [IO.File]::ReadAllText((Join-Path $core 'watcher.ps1'))
    $started = $text.IndexOf('started (pid $PID'); $loop = $text.IndexOf("while (`$true) {", [Math]::Max(0, $started))
    Assert-True ($started -gt 0 -and $loop -gt $started) 'the started log line comes before the main loop'
    Assert-Match $text.Substring($started, $loop - $started) '(?m)^Write-Alive\s*$' 'Write-Alive runs between the started line and the main loop'
}
Test-Case 'static: integration helpers never hash a file after a separate Test-Path (the watcher can delete it in between; J42)' {
    $e = $null; $t = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Test-Integration.ps1'), [ref]$t, [ref]$e)
    $fns = $ast.FindAll({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] }, $true)
    Assert-True (@($fns | Where-Object { $_.Name -eq 'Hashes' }).Count -eq 1) 'Hashes exists'
    foreach ($fn in $fns) {
        $b = $fn.Body.Extent.Text
        Assert-NotMatch $b 'Test-Path[^\r\n]*\{\s*(Sha256File|Get-FileHash)' "$($fn.Name) hashes after a Test-Path"
    }
}
Test-Case 'static: the watcher logs that it is starting, with its start-up time, before it compiles its native helpers (a cold start is visible; J42)' {
    $text = [IO.File]::ReadAllText((Join-Path $core 'watcher.ps1'))
    $starting = $text.IndexOf('starting (pid $PID, first statement'); $compile = $text.IndexOf('Add-Type -Namespace WP -Name U')
    Assert-True ($starting -gt 0 -and $compile -gt $starting) 'the starting log line precedes the first Add-Type'
    Assert-True ($text.IndexOf('$LogPath = ') -lt $starting) 'the log path is set before that line'
    Assert-Match $text.Substring($starting, 120) 'first statement \$\(Up-Ms\) ms after its process started' 'the line carries the start-up time'
}
Test-Case 'static: integration waits read the watcher log after a mark, never the whole log (a repeated case matched its previous run; J42)' {
    $text = [IO.File]::ReadAllText((Join-Path $PSScriptRoot 'Test-Integration.ps1'))
    $whole = @([regex]::Matches($text, '\(Get-Log\)\s*-(not)?match') | ForEach-Object { $_.Value })
    Assert-True ($whole.Count -eq 0) "$($whole.Count) wait(s) match the whole watcher log: use Log-Mark and Get-LogSince (or Wait-LogMatch -Since)"
}
Test-Case 'static: Handle-Hang writes hang.txt before Kill-Game and again after it (a watcher stopped mid-kill still leaves evidence; J19)' {
    $e = $null; $t = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $core 'watcher.ps1'), [ref]$t, [ref]$e)
    $fn = $ast.Find({ param($n) $n -is [Management.Automation.Language.FunctionDefinitionAst] -and $n.Name -eq 'Handle-Hang' }, $true)
    Assert-True ($null -ne $fn) 'Handle-Hang exists'
    $body = $fn.Body.Extent.Text
    $kill = $body.IndexOf('Kill-Game')
    $writes = @([regex]::Matches($body, 'Write-Atomic \$hangTxt') | ForEach-Object { $_.Index })
    Assert-True ($kill -gt 0) 'Handle-Hang calls Kill-Game'
    Assert-True ($writes.Count -eq 2 -and $writes[0] -lt $kill -and $writes[1] -gt $kill) 'hang.txt written atomically once before and once after Kill-Game'
    Assert-Match $body "kill: pending" 'the first write says the kill is pending'
    Assert-True ($body.IndexOf('HANG handled') -gt $writes[1]) 'HANG handled (the completion signal tests wait for) is logged after the final write'
}
Test-Case 'static: Test-Integration refuses -Repeat without -Only before it starts anything (J19 review)' {
    # checked statically: running the suite to see the refusal would start a watcher and kill Fake* processes if the guard broke
    $e = $null; $t = $null
    $ast = [Management.Automation.Language.Parser]::ParseFile((Join-Path $PSScriptRoot 'Test-Integration.ps1'), [ref]$t, [ref]$e)
    $first = $ast.EndBlock.Statements[0].Extent.Text
    Assert-Match $first '^if \(\$Repeat -gt 1 -and -not \$Only\)' 'the first statement is the -Repeat/-Only guard'
    Assert-Match $first 'exit 2' 'it exits before the watcher starts'
}

# ---- overlay style prefs: the game's UTF-16LE preferences file ---------------------------------------------------------------------
$u16 = New-Object Text.UnicodeEncoding($false, $false)
function Prefs-Bytes([string]$t) { return ([byte[]]@(0xFF, 0xFE) + $u16.GetBytes($t)) }
function Prefs-Text([byte[]]$b) { return $u16.GetString($b, 2, $b.Length - 2) }
$prefsTxt = "write_preferences_at_exit true; # write_preferences_at_exit <bool>, Write preferences at exit #`r`nx_res 3840; # x_res <int32>, Fixed window width #`r`ny_res 2160; # y_res <int32>, Fixed window height #`r`nx_pos 0; # x_pos <int32>, Window position #`r`ny_pos 0; # y_pos <int32>, Window position #`r`ngfx_fullscreen true; # gfx_fullscreen <bool>, Run the application in fullscreen or not #`r`nnumber_of_threads 0; # number_of_threads <int>, Set the number of threads #`r`n"
Test-Case 'overlay (prefs): only the targeted values change, comments and every other byte stay, BOM and CRLF kept' {
    $base = Prefs-Bytes $prefsTxt
    $out = Apply-Overlay $base "x_res 1920`ny_res 1080`ngfx_fullscreen false`n" 'prefs' 'headless'
    Assert-True ($out[0] -eq 0xFF -and $out[1] -eq 0xFE) 'BOM kept'
    $want = $prefsTxt.Replace('x_res 3840;', 'x_res 1920;').Replace('y_res 2160;', 'y_res 1080;').Replace('gfx_fullscreen true;', 'gfx_fullscreen false;')
    Assert-Eq (Prefs-Text $out) $want 'only the three values changed'
    $b2 = Prefs-Bytes $want
    Assert-Eq $out.Length $b2.Length 'length'
    Assert-Eq (Sha-Bytes $out) (Sha-Bytes $b2) 'byte-identical to the expected file'
    # the same values again: byte-identical to the base
    Assert-Eq (Sha-Bytes (Apply-Overlay $base "x_res 3840`ny_res=2160`n" 'prefs' 'p')) (Sha-Bytes $base) 'same values = identical bytes (also key=value syntax)'
    # a key name that is only a prefix of another key does not match it
    Assert-Eq (Prefs-Text (Apply-Overlay $base "x_re 5`n" 'prefs' 'p')).Contains('x_re 5;') $true 'a prefix of a key is a new key, not x_res'
}
Test-Case 'overlay (prefs): a missing key is appended as "key value;", an empty base becomes UTF-16LE, !key and a non-UTF-16 file are refused' {
    $base = Prefs-Bytes $prefsTxt
    Assert-Eq (Prefs-Text (Apply-Overlay $base "fix_res true`n" 'prefs' 'p')) ($prefsTxt + "fix_res true;`r`n") 'appended after the last line'
    $noNl = Prefs-Bytes "a 1; # c #"
    Assert-Eq (Prefs-Text (Apply-Overlay $noNl "b 2`n" 'prefs' 'p')) "a 1; # c #`r`nb 2;`r`n" 'a base without a final newline gets one first'
    $e0 = Apply-Overlay ([byte[]]@()) "x_res 1920`n" 'prefs' 'p'
    Assert-True ($e0[0] -eq 0xFF -and $e0[1] -eq 0xFE) 'new file starts with the UTF-16LE BOM'
    Assert-Eq (Prefs-Text $e0) "x_res 1920;`r`n" 'new file content'
    $threw = ''; try { Apply-Overlay $base "!x_res`n" 'prefs' 'p' } catch { $threw = $_.Exception.Message }
    Assert-Match $threw "'!key' is not supported" 'comment-out is refused with a clear error'
    $threw = ''; try { Apply-Overlay (Enc "x_res 1;`r`n") "x_res 2`n" 'prefs' 'p' } catch { $threw = $_.Exception.Message }
    Assert-Match $threw 'UTF-16LE' 'an 8-bit file is refused, not silently re-encoded'
    Assert-Eq (Get-PrefsValue $base 'x_pos') '0' 'Get-PrefsValue reads a value'
    Assert-Eq (Get-PrefsValue $base 'x_res') '3840' 'Get-PrefsValue x_res'
    Assert-True ($null -eq (Get-PrefsValue $base 'nope')) 'and $null for a missing key'
}

# ---- headless overlay: snapshot, overlay on top, restore byte for byte -----------------------------------------------------------------
Test-Case 'headless overlay: no active profile = snapshot + _active.json, the prefs and mod ini change only in the headless keys, restore is byte-identical; a warning when x_pos/y_pos sit inside the virtual display' {
    $real = Prefs-Bytes ($prefsTxt.Replace('x_pos 0;', 'x_pos 4000;').Replace('y_pos 0;', 'y_pos 2300;'))
    [IO.File]::WriteAllBytes($prefs, $real)
    $iniBefore = Test-Path -LiteralPath $ini
    $o = New-Object Collections.Generic.List[string]
    $h0 = Hashes
    $err = Headless-Overlay 1920 1080 'agent1' @(3839, 2160, 7679, 4320) $o
    Assert-True ($null -eq $err) "overlay ($err)"
    $act = Get-Active
    Assert-Eq $act.name 'headless' 'recorded like a profile'; Assert-Eq $act.owner 'agent1' 'owner'; Assert-Eq (@($act.history)[-1]) 'headless' 'history'
    $now = [IO.File]::ReadAllBytes($prefs)
    Assert-Eq (Prefs-Text $now) ((Prefs-Text $real).Replace('x_res 3840;', 'x_res 1920;').Replace('y_res 2160;', 'y_res 1080;').Replace('gfx_fullscreen true;', 'gfx_fullscreen false;')) 'prefs: only x_res, y_res, gfx_fullscreen changed (x_pos/y_pos untouched)'
    Assert-Match ([Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($ini))) '(?s)\[headless\].*enabled=1.*size=1920x1080' 'mod ini has the headless keys'
    Assert-Match ($o -join "`n") 'WARNING: the base preferences carry x_pos=4000 y_pos=2300' 'x_pos/y_pos inside the virtual display rect is warned about'
    # a second launch: the files already carry the keys; nothing changes, still one snapshot
    $o2 = New-Object Collections.Generic.List[string]
    Assert-True ($null -eq (Headless-Overlay 1920 1080 'agent1' $null $o2)) 'second overlay'
    Assert-Match ($o2 -join "`n") 'prefs already carries' 'idempotent'
    Assert-Match (Headless-Overlay 1920 1080 'agent2' $null $o2) 'still active' 'another owner is refused while one is active'
    $r = Profile-Restore 'test' $o2
    Assert-True ($null -eq $r) "restore ($r)"
    Assert-Eq (Sha256File $prefs) (Sha-Bytes $real) 'prefs byte-identical after the restore'
    Assert-Eq (Hashes) $h0 'every file back to the baseline'
    Assert-True ($null -eq (Get-Active)) 'nothing active'
    [IO.File]::WriteAllBytes($prefs, $odd)
}
Test-Case 'headless overlay on top of an active profile keeps the profile in force and the snapshot base' {
    $o = New-Object Collections.Generic.List[string]
    Assert-True ($null -eq (Profile-Apply 'proxy-dxvk' 'agent1' $o)) 'profile'
    $snap = (Get-Active).snapshot
    [IO.File]::WriteAllBytes($prefs, (Prefs-Bytes $prefsTxt))
    $h = Hashes
    Assert-True ($null -eq (Headless-Overlay 3840 2160 'agent1' $null $o)) 'overlay'
    $act = Get-Active
    Assert-Eq $act.name 'proxy-dxvk' 'the profile stays the active one'; Assert-Eq $act.snapshot $snap 'same snapshot'; Assert-Eq (@($act.history)[-1]) 'headless' 'history records headless'
    Assert-Match ([Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($ini))) '(?m)^backend=dxvk' 'the profile content is still there'
    Assert-Match ([Text.Encoding]::ASCII.GetString([IO.File]::ReadAllBytes($ini))) 'enabled=1' 'with the headless keys on top'
    Assert-True ($null -eq (Profile-Restore 'test' $o)) 'restore'
    [IO.File]::WriteAllBytes($prefs, $odd)
}

# ---- the display tool's pure logic: nothing but the virtual display is ever selected -----------------------------------------------------------
. (Join-Path $core 'vdisplay_probe.ps1') -LibOnly
function FD([string]$dev, [string]$adapter, [string]$mon, [bool]$primary, [int]$w, [int]$h, [int]$x, [int]$y, [int]$hz = 60) { return [pscustomobject]@{ Device = $dev; Adapter = $adapter; Monitor = $mon; Primary = $primary; W = $w; H = $h; Hz = $hz; X = $x; Y = $y } }
$VDD = 'Virtual Display Driver'
$topoA = @((FD '\\.\DISPLAY1' 'NVIDIA GeForce RTX 4090' 'Generic PnP Monitor' $true 3840 2160 0 0 240), (FD '\\.\DISPLAY2' 'NVIDIA GeForce RTX 4090' 'Dell S2721DGF (HDMI2)' $false 2560 1440 -2560 327 144), (FD '\\.\DISPLAY10' $VDD 'Generic PnP Monitor' $false 3840 2160 3839 2160))
$topoB = @((FD '\\.\DISPLAY1' 'NVIDIA GeForce RTX 4090' 'Dell S2721DGF (HDMI2)' $true 2560 1440 0 0 144), (FD '\\.\DISPLAY12' $VDD 'Generic PnP Monitor' $false 3840 2160 2560 1440))
Test-Case 'display tool: the cursor goes back only when Windows recentred it on a display (a move Liam made is left alone)' {
    $disp = @([pscustomobject]@{ X = 0; Y = 0; W = 3840; H = 2160 }, [pscustomobject]@{ X = 3839; Y = 2160; W = 1920; H = 1080 })
    Assert-True (Get-CursorDecision @(1226, 1201) @(1920, 1080) $disp) 'moved to the primary centre: put back'
    Assert-True (Get-CursorDecision @(10, 10) @(4799, 2700) $disp) 'moved to the virtual display centre: put back'
    Assert-True (-not (Get-CursorDecision @(1920, 1080) @(1920, 1080) $disp)) 'not moved: nothing to do'
    Assert-True (-not (Get-CursorDecision @(1226, 1201) @(700, 900) $disp)) 'moved elsewhere (Liam): left alone'
}
Test-Case 'display selection: both of Liam''s topologies select the virtual display (by name, wherever its origin or GDI number is)' {
    $a = Select-VirtualDisplay $topoA $VDD
    Assert-Eq $a.display.Device '\\.\DISPLAY10' 'topology A: 4K primary + Dell + VDD at 3839,2160'
    $b = Select-VirtualDisplay $topoB $VDD
    Assert-Eq $b.display.Device '\\.\DISPLAY12' 'topology B: Dell primary at 0,0 + VDD at 2560,1440'
    $m = @((FD '\\.\DISPLAY1' 'NVIDIA' 'Generic PnP Monitor' $true 3840 2160 0 0), (FD '\\.\DISPLAY7' 'Some Indirect Adapter' $VDD $false 1920 1080 3840 0))
    Assert-Eq (Select-VirtualDisplay $m $VDD).display.Device '\\.\DISPLAY7' 'a match on the monitor string works too'
}
Test-Case 'display selection: no virtual display, two of them, or one marked primary select NOTHING (no fallback by size, index or DISPLAYn)' {
    $none = @($topoA[0], $topoA[1])
    $r = Select-VirtualDisplay $none $VDD
    Assert-True ($null -eq $r.display) 'no VDD: nothing selected'; Assert-Match $r.reason 'no attached display matches' 'reason'
    # a real 4K display, same size as the wanted mode, is never taken for the virtual one
    Assert-True ($null -eq (Select-VirtualDisplay @($topoA[0]) $VDD).display) 'a 4K primary alone: nothing'
    $two = @($topoA[0], $topoA[2], (FD '\\.\DISPLAY11' $VDD 'Generic PnP Monitor' $false 3840 2160 7679 0))
    $r = Select-VirtualDisplay $two $VDD
    Assert-True ($null -eq $r.display) 'two VDDs: nothing'; Assert-Match $r.reason 'not unique' 'reason says not unique'
    $prim = @((FD '\\.\DISPLAY1' 'NVIDIA' 'Dell' $false 2560 1440 -2560 0), (FD '\\.\DISPLAY10' $VDD 'Generic PnP Monitor' $true 3840 2160 0 0))
    $r = Select-VirtualDisplay $prim $VDD
    Assert-True ($null -eq $r.display) 'VDD marked primary: nothing'; Assert-Match $r.reason 'PRIMARY' 'reason says primary'
    Assert-True ($null -eq (Select-VirtualDisplay $topoA '').display) 'an empty name selects nothing (it would match everything)'
    Assert-True ($null -eq (Select-VirtualDisplay @() $VDD).display) 'an empty list'
    foreach ($t in @($topoA, $topoB, $none, $two, $prim)) {
        $s = Select-VirtualDisplay $t $VDD
        if ($s.display) { Assert-True (-not $s.display.Primary) 'a selection is never primary'; Assert-Match ($s.display.Adapter + $s.display.Monitor) 'Virtual Display Driver' 'and always matches the name' }
    }
}
Test-Case 'display tool: -Origin plans refuse any rect that overlaps another display (touching is fine), -Set candidates, change detection' {
    $sel = Select-VirtualDisplay $topoA $VDD
    Assert-True (Get-OriginPlan $topoA $sel 3840 0).ok 'right of the 4K primary, touching its edge'
    Assert-True (Get-OriginPlan $topoA $sel 3839 2160).ok 'the corner-touching origin seen on 2026-10-29'
    $p = Get-OriginPlan $topoA $sel 0 0
    Assert-True (-not $p.ok) 'on top of the primary: refused'; Assert-Match $p.reason 'overlaps \\\\.\\DISPLAY1' 'names the display it overlaps'
    Assert-True (-not (Get-OriginPlan $topoA $sel -2000 400).ok) 'on top of the Dell: refused'
    $none2 = Select-VirtualDisplay @($topoA[0]) $VDD
    Assert-True (-not (Get-OriginPlan @($topoA[0]) $none2 5000 0).ok) 'no selection: no plan'
    Assert-Match (Get-OriginPlan @($topoA[0]) $none2 9000 0).reason 'no attached display' 'the selection reason is passed through'
    Assert-Eq (Get-HzCandidates 0 240 | ForEach-Object { $_ }) '240 60' 'current rate first, then 60'
    Assert-Eq (Get-HzCandidates 0 60 | ForEach-Object { $_ }) '60' 'no duplicates'
    Assert-Eq (Get-HzCandidates 120 60 | ForEach-Object { $_ }) '120' 'an explicit rate is the only candidate'
    $after = @($topoA[0], (FD '\\.\DISPLAY2' 'NVIDIA GeForce RTX 4090' 'Dell S2721DGF (HDMI2)' $false 2560 1440 -2560 400 144), (FD '\\.\DISPLAY10' $VDD 'Generic PnP Monitor' $false 1920 1080 3839 2160))
    $c = @(Get-OtherChanges $topoA $after '\\.\DISPLAY10')
    Assert-Eq $c.Count 1 'only the Dell moved (the virtual display itself is excluded)'; Assert-Match $c[0] 'DISPLAY2 changed' 'names it'
    Assert-Eq @(Get-OtherChanges $topoA $topoA '\\.\DISPLAY10').Count 0 'no change = nothing reported'
    Assert-Eq (Parse-Size '3840x2160').w 3840 'Parse-Size'; Assert-True ($null -eq (Parse-Size '3840')) 'bad size'; Assert-True ($null -eq (Parse-Size '1x1')) 'too small'
}
Test-Case 'display tool: -Check/-Set/-Origin/-Restore all select by name and refuse without a selection (static)' {
    $t = [IO.File]::ReadAllText((Join-Path $core 'vdisplay_probe.ps1'))
    foreach ($mode in 'if ($Check)', 'if ($Set)', 'if ($Origin)', 'if ($Restore)') {
        $i = $t.IndexOf($mode); Assert-True ($i -gt 0) "mode $mode exists"
        $seg = $t.Substring($i, [Math]::Min(900, $t.Length - $i))
        Assert-Match $seg 'if \(-not \$sel\.display\)' "$mode refuses without a selected virtual display"
    }
    Assert-NotMatch $t 'DISPLAY\d' 'no hard-coded DISPLAYn'
}

# ---- the headless gate in the watcher's launch --------------------------------------------------------------------------------------------
Test-Case 'headless: the adapter block is read, and the launch refuses a d3d9.dll without the status-file marker' {
    Assert-Eq $A.headless.default_size '3840x2160' 'default size'
    Assert-Eq $A.headless.exit_code 2160 'exit code'
    Assert-Eq $A.headless.prefs['x_res'] '{W}' 'prefs template'
    Assert-Eq $A.headless.mod_ini['headless.size'] '{W}x{H}' 'mod ini template'
    $dll = Join-Path $A.game_dir 'd3d9.dll'
    Remove-Item -LiteralPath $dll -Force -ErrorAction SilentlyContinue
    $o = New-Object Collections.Generic.List[string]
    Assert-Match (Headless-Prepare '3840x2160' 3840 2160 'agent1' $o) 'does not contain .headless_status\.json' 'no d3d9.dll at all'
    [IO.File]::WriteAllBytes($dll, $Latin1.GetBytes('MZ old proxy without the marker'))
    Assert-Match (Headless-Prepare '3840x2160' 3840 2160 'agent1' $o) 'cannot run headless' 'an older proxy'
    Assert-True ($null -eq (Get-Active)) 'and nothing was overlaid'
    Assert-True (Bytes-Contain ([byte[]]($Latin1.GetBytes('xx headless_status.json yy'))) 'headless_status.json') 'Bytes-Contain'
    Remove-Item -LiteralPath $dll -Force
}
Remove-Item -LiteralPath $tmp -Recurse -Force -ErrorAction SilentlyContinue
exit (Finish-Tests 'unit')
