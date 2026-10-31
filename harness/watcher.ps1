# purpose: the PC watcher: runs job requests dropped into <root>\jobs\ by agents through harness/core/job.sh (control jobs launch/kill/profile/status/noop/restart/update, cmd and ps1 scripts) one at a time, enforces the game lock, watches the game for hangs, restores config profiles byte for byte
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File watcher.ps1 [-Root <dir>] [-Adapter <adapter.json>]   (started by watch.cmd; protocol, layout and settings: harness/README.md)
# when: runs permanently on the PC after "Install watcher.cmd"; agents never start it, they submit jobs with harness/core/job.sh
# not-a-verb: a Windows PowerShell 5.1 service loop that runs on the PC, not a repo operation
# Ported by design (not line by line) from empire-remastered rml_mod/src/watch5.ps1. Game-agnostic: everything about the game comes from adapter.json.
# Exit codes (read by watch.cmd): 3 = restart me (re-reads this file), 4 = restart the launcher too, 10 = another watcher owns this root, 11 = stopped on request.
# ASCII only on purpose: Windows PowerShell 5.1 reads a script without a BOM as ANSI. Data files are written as UTF-8 WITHOUT a BOM, never UTF-16.
param([string]$Root = '', [string]$Adapter = '', [switch]$NoRun)

$ErrorActionPreference = 'Stop'
$Version = '1.2.0'
$SrcDir = $PSScriptRoot
if (-not $Root) { $Root = Join-Path $SrcDir '..' }
$Root = [IO.Path]::GetFullPath($Root).TrimEnd('\', '/')
if (-not $Adapter) { $Adapter = Join-Path $SrcDir 'adapter.json' }
$Latin1 = [Text.Encoding]::GetEncoding(28591)          # byte-transparent: batch files and overlays keep their exact bytes
$Utf8 = New-Object Text.UTF8Encoding $false            # UTF-8 WITHOUT a BOM (the 5.1 'UTF8' name writes one)
$Inv = [Globalization.CultureInfo]::InvariantCulture
$IsWin = ($PSVersionTable.PSEdition -ne 'Core') -or ($IsWindows -eq $true)

# ------------------------------------------------------------------------------------------------ settings ----------
$Defaults = [ordered]@{
    hang_s            = 120     # no CPU progress and no heartbeat-file write for this long = hung
    hang_startup_s    = 180     # never in the first N s after the process started (loading)
    hung_window_s     = 60      # IsHungAppWindow continuously true for this long = hung (a long load can block the message pump for a while)
    cpu_epsilon_s     = 0.01    # CPU-time growth between two samples that counts as progress
    dump_wait_s       = 90      # the out-of-process minidump may take this long
    dump_type         = '0x1165'  # DataSegs|HandleData|UnloadedModules|IndirectlyReferencedMemory|ProcessThreadData|ThreadInfo
    watchdog          = 1       # 0 = off (also: <root>\watchdog.off, or hang_s=0 in game.lock)
    zombie_wait_s     = 15      # after taskkill /F /T a process still listed after this long = zombie
    job_timeout_s     = 1800
    prune_hours       = 24
    lock_stale_min    = 20
    job_script_guard  = 'refuse'  # a script that starts/kills the game or writes a config file without #job owner=: refuse | warn
    exe_check         = 'refuse'  # the game exe's sha1 against exe_identity.json beside adapter.json before every launch: refuse | warn (J18)
    launch_confirm_s  = 20
    loop_ms           = 1000
    test_hooks        = 0       # tests only: enables '#job test=...' hooks
    test_fake_zombie  = 0       # tests only: kill skips the real kill, to exercise the zombie path
    test_vdisplay_script = ''   # tests only (needs test_hooks=1): a script that stands in for vdisplay_probe.ps1 (the CI runner has no virtual display)
    winprobe          = 1       # 0 = a launch does not start win_probe.ps1 (the whole-launch window probe)
}
$S = @{}
$IniStamp = $null
function Load-Settings {
    $script:S = @{}
    foreach ($k in $Defaults.Keys) { $script:S[$k] = $Defaults[$k] }
    $ini = Join-Path $Root 'watcher.ini'
    if (Test-Path -LiteralPath $ini) {
        foreach ($line in [IO.File]::ReadAllLines($ini)) {
            $t = $line.Trim()
            if (-not $t -or $t.StartsWith('#') -or $t.StartsWith(';') -or $t.StartsWith('[')) { continue }
            $kv = $t -split '=', 2
            if ($kv.Count -eq 2) { $script:S[$kv[0].Trim()] = $kv[1].Trim() }
        }
        $script:IniStamp = (Get-Item -LiteralPath $ini).LastWriteTimeUtc
    } else { $script:IniStamp = $null }
}
function IntSet([string]$k) { $v = 0; if ([int]::TryParse([string]$S[$k], [ref]$v)) { return $v }; return [int]$Defaults[$k] }
function NumSet([string]$k) { return [double]::Parse([string]$S[$k], $Inv) }

# ------------------------------------------------------------------------------------------------ adapter -----------
$A = $null
function Load-Adapter {
    $j = [IO.File]::ReadAllText($Adapter, $Utf8) | ConvertFrom-Json
    $x = @{}
    $x.game = [string]$j.game
    $x.title = [string]$j.title
    $x.game_dir = [Environment]::ExpandEnvironmentVariables([string]$j.game_dir).TrimEnd('\', '/')
    $x.appdata_dir = [Environment]::ExpandEnvironmentVariables([string]$j.appdata_dir).TrimEnd('\', '/')
    $x.game_image = [string]$j.game_image
    $x.other_images = @(@($j.other_images) | Where-Object { $_ })
    $x.launch_route = [string]$j.launch.route
    $x.launch_exe = [string]$j.launch.exe
    $x.launch_args = [string]$j.launch.args
    $x.steam_uri = [string]$j.launch.steam_uri
    $x.steam_wait_s = [int]$j.launch.steam_wait_s
    $x.heartbeat_files = @(@($j.heartbeat_files) | Where-Object { $_ })
    $x.archive_dirs_log = @(@($j.archive.dirs_log) | Where-Object { $_ })
    $x.archive_dirs_dump = @(@($j.archive.dirs_dump) | Where-Object { $_ })
    $x.archive_files = @(@($j.archive.files) | Where-Object { $_ })
    $x.virtualstore_guard = @(@($j.virtualstore_guard) | Where-Object { $_ })
    $x.foreign_locks = @(@($j.foreign_locks) | Where-Object { $_ } | ForEach-Object { [Environment]::ExpandEnvironmentVariables([string]$_) })
    $x.headless = $null
    if ($j.headless) {
        $h = $j.headless
        $pm = [ordered]@{}; if ($h.prefs) { foreach ($pr in $h.prefs.PSObject.Properties) { $pm[$pr.Name] = [string]$pr.Value } }
        $mm = [ordered]@{}; if ($h.mod_ini) { foreach ($pr in $h.mod_ini.PSObject.Properties) { $mm[$pr.Name] = [string]$pr.Value } }
        $x.headless = @{
            display_name = [string]$h.display_name; default_size = [string]$h.default_size; status_file = [string]$h.status_file
            marker_file = [string]$h.marker_file; marker = [string]$h.marker; exit_code = [int]$h.exit_code; prefs = $pm; mod_ini = $mm
        }
    }
    $x.config_files = @(@($j.config_files) | ForEach-Object { @{ id = [string]$_.id; anchor = [string]$_.anchor; path = [string]$_.path; style = [string]$_.style } })
    $script:A = $x
}
function Target-Path($t) {
    $base = if ($t.anchor -eq 'appdata') { $A.appdata_dir } else { $A.game_dir }
    return (Join-Path $base $t.path)
}
function GamePath([string]$rel) { return (Join-Path $A.game_dir $rel) }
function RootPath([string]$rel) { return (Join-Path $Root $rel) }

# ------------------------------------------------------------------------------------------------ utilities ---------
function UtcNow { return (Get-Date).ToUniversalTime() }
# Always UTC, always invariant culture (a ':' time separator is culture-dependent), always labelled with the Z suffix.
function UtcStr($d) { if ($null -eq $d) { return $null }; return ([DateTime]$d).ToUniversalTime().ToString('yyyy-MM-dd\THH:mm:ss\Z', $Inv) }
function UtcStamp($d) { return ([DateTime]$d).ToUniversalTime().ToString('yyyyMMdd\THHmmss\Z', $Inv) }
$LogPath = Join-Path $Root 'watcher.log'
function Log([string]$msg) {
    $line = '[' + (UtcStr (Get-Date)) + '] ' + $msg
    try { Write-Host $line } catch { }
    for ($i = 0; $i -lt 5; $i++) {
        try {
            if ((Test-Path -LiteralPath $LogPath) -and (Get-Item -LiteralPath $LogPath).Length -gt 2MB) {
                Move-Item -LiteralPath $LogPath -Destination "$LogPath.1" -Force
            }
            [IO.File]::AppendAllText($LogPath, $line + "`r`n", $Utf8); return
        } catch { Start-Sleep -Milliseconds 50 }
    }
}
function Move-Into([string]$from, [string]$to) {
    for ($i = 0; $i -lt 20; $i++) {
        try {
            if (Test-Path -LiteralPath $to) { [IO.File]::Replace($from, $to, [NullString]::Value) } else { [IO.File]::Move($from, $to) }
            return
        } catch { if ($i -eq 19) { throw }; Start-Sleep -Milliseconds 100 }
    }
}
function Write-Atomic([string]$path, [string]$text) {
    $tmp = "$path.wtmp"
    [IO.File]::WriteAllText($tmp, $text, $Utf8)
    Move-Into $tmp $path
}
function Write-AtomicBytes([string]$path, [byte[]]$bytes) {
    $tmp = "$path.wtmp"
    [IO.File]::WriteAllBytes($tmp, $bytes)
    Move-Into $tmp $path
}
function Read-Shared([string]$path) {
    # Always returns a [byte[]], also for a 0-byte file. The unary comma matters: a plain 'return $ms.ToArray()' is unrolled by
    # PowerShell, so 0 bytes came back as $null, 1 byte as a scalar and N bytes as an object[] (the earlier remaster's watcher 5.0 wedged its queue on
    # an empty job output, 2026-10-21).
    $fs = New-Object IO.FileStream($path, [IO.FileMode]::Open, [IO.FileAccess]::Read, [IO.FileShare]'ReadWrite,Delete')
    try { $ms = New-Object IO.MemoryStream; $fs.CopyTo($ms); return ,$ms.ToArray() } finally { $fs.Dispose() }
}
# A file that is replaced every few seconds (watcher.status) can be caught mid-swap: retry before believing it is broken.
function Read-JsonRetry([string]$path, [int]$tries = 8) {
    for ($i = 0; $i -lt $tries; $i++) {
        try { $b = Read-Shared $path; if ($b.Length -gt 0) { return ($Utf8.GetString($b) | ConvertFrom-Json) } } catch { }
        Start-Sleep -Milliseconds 100
    }
    return $null
}
# Liveness comes from the heartbeat file's mtime, not from parsing watcher.status (which can be mid-swap).
function Get-AliveAgeS([string]$root) {
    try { return ((Get-Date) - (Get-Item -LiteralPath (Join-Path $root 'watcher.alive')).LastWriteTime).TotalSeconds } catch { return $null }
}
function Sha([string]$path) { return (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLower() }
function Sha-Bytes([byte[]]$b) {
    $h = [Security.Cryptography.SHA256]::Create()
    try { return ([BitConverter]::ToString($h.ComputeHash($b)).Replace('-', '').ToLower()) } finally { $h.Dispose() }
}
function Parse-KV([string]$txt) {
    $h = @{}
    if (-not $txt) { return $h }
    foreach ($m in [regex]::Matches($txt, '(?<![\w.\-])([A-Za-z_][\w.\-]*)=(.*?)(?=\s+[A-Za-z_][\w.\-]*=|\r|\n|$)')) {
        $k = $m.Groups[1].Value
        if (-not $h.ContainsKey($k)) { $h[$k] = $m.Groups[2].Value.Trim().Trim('"') }
    }
    return $h
}
function Remove-Quiet([string]$p) { try { if (Test-Path -LiteralPath $p) { Remove-Item -LiteralPath $p -Force -Recurse } } catch { } }
function Is-ValidId([string]$id) { return $id -match '^[A-Za-z0-9][A-Za-z0-9._\-]{0,119}$' }
function ToDelete([string]$sub) {
    $d = RootPath (Join-Path '_to_delete' $sub)
    if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    return $d
}
function Img-Base([string]$img) { return [IO.Path]::GetFileNameWithoutExtension($img) }
function Up-Ms { try { return [int]((Get-Date) - (Get-Process -Id $PID).StartTime).TotalMilliseconds } catch { return -1 } }

if ($IsWin) {
    # the first log line, with the time powershell.exe took to reach it: on fresh CI runners a new watcher process reached its main
    # loop 17 to 35 s after it started (J42 runs on 66d0fd9 and 97358f5), while a warm load of this script takes under 3 s and the
    # compile under 2 s, so the time goes before the first statement (host start-up, script scan and parse); this line and the next
    # record the split, and a reader of the log can tell a watcher that is still starting from one that never started
    $t0 = Get-Date
    Log "watcher $Version starting (pid $PID, first statement $(Up-Ms) ms after its process started): compiling native helpers (Add-Type)"
    Add-Type -Namespace WP -Name U -MemberDefinition @'
[DllImport("user32.dll")] public static extern bool IsIconic(IntPtr h);
[DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h);
[DllImport("user32.dll")] public static extern bool IsHungAppWindow(IntPtr h);
'@
    Log "watcher: native helpers compiled in $([int]((Get-Date) - $t0).TotalMilliseconds) ms"
}

# ------------------------------------------------------------------------------------------------ state -------------
$JobsDir = Join-Path $Root 'jobs'
$ProfilesDir = Join-Path $Root 'profiles'
$SavedDir = Join-Path $ProfilesDir '_saved'
$ActivePath = Join-Path $ProfilesDir '_active.json'
$StatusPath = Join-Path $Root 'watcher.status'
$AlivePath = Join-Path $Root 'watcher.alive'
$ZombiePath = Join-Path $Root 'watcher.zombie.json'
$IdsPath = Join-Path $JobsDir '_ids.txt'
$StartedAt = Get-Date
$Cur = $null                 # the job in the single execution slot
$LaunchAt = $null            # last launch by this watcher (arms the watchdog for that process)
$Game = @{ state = 'not_running'; pid = $null; window = $null; cpu_idle_s = $null; log_idle_s = $null; armed = $false }
$Track = @{ pid = 0; cpu = $null; cpu_at = $null; hung_since = $null }
$Zombie = $null
$LastHang = $null
$LastPrune = (Get-Date).AddHours(-1)
$LastAlive = (Get-Date).AddMinutes(-1)
$RestartAfter = $null        # 3 / 4 / 11 once the slot is idle
$PendingRestoreLogged = $false
$LockSeen = $null
$PumpDepth = 0
$VdRetryAt = Get-Date        # next time a failed virtual-display restore may be retried
Load-Settings
if (Test-Path -LiteralPath $Adapter) { Load-Adapter }

# ------------------------------------------------------------------------------------------------ game lock ---------
# game.lock: ONE line: owner=<you> session=<id> purpose=<text> started=<UTC> [hang_s=<n>]. Its mtime is the refresh time.
function Get-Lock {
    $p = RootPath 'game.lock'
    if (-not (Test-Path -LiteralPath $p)) { return $null }
    try { $fi = Get-Item -LiteralPath $p; $b = Read-Shared $p } catch { return $null }
    if ($b.Length -eq 0) { return $null }                      # 0 bytes = being written: treated as absent
    $kv = Parse-KV ($Latin1.GetString($b))
    $age = ((Get-Date) - $fi.LastWriteTime).TotalSeconds
    return [pscustomobject]@{
        owner = $kv['owner']; session = $kv['session']; purpose = $kv['purpose']; started = $kv['started']
        hang_s = $kv['hang_s']; age_s = [int]$age; stale = ($age -gt (IntSet 'lock_stale_min') * 60); path = $p
    }
}
function Check-Owner([string]$owner) {
    $l = Get-Lock
    if (-not $l) { return 'no game.lock is held. Take <root>\game.lock first (one line: owner=<you> session=<id> purpose=<text> started=<UTC>), then send owner=<you> with the request' }
    if ($l.stale) { return "game.lock (owner=$($l.owner)) is stale ($($l.age_s) s since its last refresh) and is being expired; take the lock again" }
    if (-not $l.owner) { return 'game.lock has no owner= field; rewrite it as owner=<you> session=<id> purpose=<text> started=<UTC>' }
    if (-not $owner) { return "the request carries no owner=, and game.lock is held by '$($l.owner)' (purpose: $($l.purpose)). Add owner=<lock owner> to the request" }
    if ($owner -ne $l.owner) { return "owner=$owner does not hold the game: game.lock owner is '$($l.owner)' (purpose: $($l.purpose), $($l.age_s) s since refresh)" }
    return $null
}
function Expire-StaleLock {
    $l = Get-Lock
    if (-not $l -or -not $l.stale) { return }
    $name = "game.lock.expired_$($l.owner -replace '[^\w.\-]', '_')_$(UtcStamp (Get-Date))"
    try { Move-Item -LiteralPath $l.path -Destination (Join-Path (ToDelete '') $name) -Force } catch { Log "lock: could not expire game.lock: $($_.Exception.Message)"; return }
    $act = Get-Active
    $tail = ''
    if ($act) { $tail = " Profile '$($act.name)' is active for owner=$($act.owner): it is restored under that owner as soon as the game is closed." }
    Log "LOCK EXPIRED: game.lock owner=$($l.owner) purpose=$($l.purpose) was not refreshed for $([int]($l.age_s / 60)) min (limit $($S.lock_stale_min)); moved to _to_delete\$name.$tail"
}
# One game at a time across titles (D11): a lock another watcher on this PC holds (e.g. the earlier remaster's rml_mod\game.lock) blocks a launch. Read only, never written.
function Foreign-LockReason {
    foreach ($p in $A.foreign_locks) {
        if (-not (Test-Path -LiteralPath $p)) { continue }
        try {
            $fi = Get-Item -LiteralPath $p
            if (((Get-Date) - $fi.LastWriteTime).TotalMinutes -gt (IntSet 'lock_stale_min')) { continue }
            $b = Read-Shared $p; if ($b.Length -eq 0) { continue }
            $kv = Parse-KV ($Latin1.GetString($b))
            return "another watcher on this PC holds a game lock ($p, owner=$($kv['owner']), purpose=$($kv['purpose'])); one game at a time"
        } catch { }
    }
    return $null
}

# ------------------------------------------------------------------------------------------------ processes ---------
function Get-ImageProcs([string]$img) { return @(Get-Process -Name (Img-Base $img) -ErrorAction SilentlyContinue) }
function Get-GameProcs { return (Get-ImageProcs $A.game_image) }
function Get-AllGameProcs {
    # both titles: [{image, pid}]
    $r = @()
    foreach ($img in (@($A.game_image) + @($A.other_images))) { foreach ($p in (Get-ImageProcs $img)) { $r += [pscustomobject]@{ image = $img; pid = $p.Id } } }
    return $r
}
function Game-Running-Reason {
    $all = @(Get-AllGameProcs)
    if (-not $all.Count) { return $null }
    return 'already running: ' + ((@($all | ForEach-Object { "$($_.image) (pid $($_.pid))" })) -join ', ')
}
function Zombie-Reason {
    if ($Zombie) { return "PC NEEDS REBOOT: zombie $($Zombie.image) pid $($Zombie.pid) survived taskkill /F at $($Zombie.since) (watcher.status zombie=true); do not launch, tell Liam" }
    return $null
}
function Kill-Tree-Except([int]$rootPid, [string[]]$keepImages) {
    # kills a job's process tree but never the game (a job may have started it as its own child)
    $all = @(Get-CimInstance Win32_Process -Property ProcessId, ParentProcessId, Name)
    $kids = @{}
    foreach ($p in $all) { $k = [int]$p.ParentProcessId; if (-not $kids.ContainsKey($k)) { $kids[$k] = @() }; $kids[$k] += $p }
    $order = New-Object Collections.ArrayList
    $stack = New-Object Collections.Stack; $stack.Push($rootPid)
    $seen = @{}
    while ($stack.Count) {
        $id = [int]$stack.Pop(); if ($seen.ContainsKey($id)) { continue }; $seen[$id] = 1
        [void]$order.Add($id)
        if ($kids.ContainsKey($id)) { foreach ($c in $kids[$id]) { if ($keepImages -notcontains $c.Name) { $stack.Push([int]$c.ProcessId) } } }
    }
    $order.Reverse()
    foreach ($id in $order) { try { Stop-Process -Id $id -Force -ErrorAction Stop } catch { } }
}
function Kill-Game([string]$why, $out) {
    $targets = @(Get-GameProcs)
    if (-not $targets.Count) { $out.Add('nothing to kill: no game process'); return $true }
    foreach ($p in $targets) {
        if ((IntSet 'test_fake_zombie') -eq 1) { $out.Add("TEST: test_fake_zombie=1, not killing $($p.ProcessName) pid $($p.Id)"); continue }
        $r = & taskkill.exe /F /T /PID $p.Id 2>&1 | Out-String
        $out.Add("taskkill /F /T /PID $($p.Id) ($($p.ProcessName)): $($r.Trim())")
    }
    $deadline = (Get-Date).AddSeconds((IntSet 'zombie_wait_s'))
    $left = @()
    do {
        Pump
        $left = @($targets | Where-Object { Get-Process -Id $_.Id -ErrorAction SilentlyContinue })
        if (-not $left.Count) { break }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)
    if ($left.Count) {
        $z = $left[0]
        $script:Zombie = [pscustomobject]@{ pid = $z.Id; image = "$($z.ProcessName).exe"; since = (UtcStr (Get-Date)); why = $why }
        Write-Atomic $ZombiePath ($Zombie | ConvertTo-Json)
        $msg = "ZOMBIE: $($z.ProcessName).exe pid $($z.Id) is still listed $($S.zombie_wait_s) s after taskkill /F /T ($why). PC needs reboot before the game can run again; launches are refused until this process is gone."
        Log ('!' * 100); Log $msg; Log ('!' * 100)
        $out.Add($msg)
        return $false
    }
    $out.Add("killed: $(@($targets | ForEach-Object { "$($_.ProcessName) $($_.Id)" }) -join ', ')")
    return $true
}

# ------------------------------------------------------------------------------------------------ launch ------------
# ------------------------------------------------------------------------------------------------ exe identity ------
# J18 (J5 ledger row 28, D2: the exe stays vanilla on disk): the game exe is hashed before every launch and compared with the sha1 in
# exe_identity.json (pc_deploy.py stages it beside adapter.json from proxy/<adapter>/identity.json). The hash is cached by size + mtime.
$ExeCache = $null
$ExeState = $null
function Exe-IdentityPath { return (Join-Path (Split-Path -Parent $Adapter) 'exe_identity.json') }
function Exe-Check {
    $exe = GamePath $A.game_image
    $want = $null
    $idp = Exe-IdentityPath
    if (Test-Path -LiteralPath $idp) { try { $want = ([string](([IO.File]::ReadAllText($idp, $Utf8)) | ConvertFrom-Json).sha1).ToLower() } catch { $want = $null } }
    $sha = $null; $ok = $null
    if (-not (Test-Path -LiteralPath $exe)) { $detail = "the game exe $exe is not there" }
    else {
        $it = Get-Item -LiteralPath $exe
        $key = "$($it.Length)|$($it.LastWriteTimeUtc.Ticks)"
        if (-not $ExeCache -or $ExeCache.key -ne $key) { $script:ExeCache = @{ key = $key; sha1 = (Get-FileHash -LiteralPath $exe -Algorithm SHA1).Hash.ToLower() } }
        $sha = $ExeCache.sha1
        if (-not $want) { $detail = "no exe identity to check $($A.game_image) against ($idp missing or unreadable: install a harness kit built by pc_deploy.py)" }
        elseif ($sha -eq $want) { $ok = $true; $detail = "$($A.game_image) sha1 $sha is the vanilla build in exe_identity.json" }
        else { $ok = $false; $detail = "MISMATCH: $($A.game_image) sha1 $sha is not the vanilla build in exe_identity.json ($want): a Steam update or a modified exe; a new identity.json from proxy/tools/exe_info.py is Liam's call" }
    }
    $script:ExeState = [ordered]@{ sha1 = $sha; ok = $ok; checked_utc = (UtcStr (Get-Date)); expected = $want; detail = $detail }
    return $script:ExeState
}
# The launch gate: $null to go ahead (a warning in $out under exe_check=warn), else the refusal.
function Exe-Gate($out) {
    $x = Exe-Check
    if ($x.ok -eq $true) { $out.Add("exe check: ok, $($x.detail)"); return $null }
    if ($S.exe_check -eq 'warn') { $out.Add("WARNING (watcher): exe check failed, launching anyway (exe_check=warn): $($x.detail)"); Log "exe check (warn): $($x.detail)"; return $null }
    Log "exe check: launch refused: $($x.detail)"
    return "EXE CHECK: $($x.detail) - launch refused (exe_check=refuse in watcher.ini; D2: the exe stays vanilla on disk)"
}

# Routes: exe = start the game exe directly (needs the Steam client running); steam = steam://rungameid/<id> (Steam starts it; the game is not our child).
# UAC file virtualization (J44, J12 fix 1g): after one failed write under Program Files a 32-bit game's later writes there go to
# %LOCALAPPDATA%\VirtualStore\<game path>\..., and the watcher reads the stale real files (heartbeats, the headless status). Before every
# launch, whoever asks for it, the copies of the adapter's virtualstore_guard folders (game-relative) are moved to _to_delete\ (nothing
# is deleted) and named in the job output ("virtualstore: moved ..."). $env:WSP_VIRTUALSTORE_ROOT replaces the VirtualStore folder (tests).
function Clear-VirtualStore($out) {
    $base = if ($env:WSP_VIRTUALSTORE_ROOT) { $env:WSP_VIRTUALSTORE_ROOT } elseif ($env:LOCALAPPDATA) { Join-Path $env:LOCALAPPDATA 'VirtualStore' } else { $null }
    if (-not $base -or -not @($A.virtualstore_guard).Count) { return }
    $q = Split-Path -NoQualifier $A.game_dir
    foreach ($d in $A.virtualstore_guard) {
        $vs = (Join-Path (Join-Path $base $q) $d).TrimEnd('\')
        if (-not (Test-Path -LiteralPath $vs)) { continue }
        $files = @(Get-ChildItem -LiteralPath $vs -Recurse -File -Force -ErrorAction SilentlyContinue)
        if (-not $files.Count) { continue }
        $dest = ToDelete ('virtualstore_' + (Get-Date).ToUniversalTime().ToString('yyyyMMdd\THHmmss\Z', $Inv))
        $names = @()
        foreach ($f in $files) {
            $rel = $f.FullName.Substring($vs.Length).TrimStart('\')
            $t = Join-Path (Join-Path $dest $d) $rel
            New-Item -ItemType Directory -Path (Split-Path $t) -Force | Out-Null
            Move-Item -LiteralPath $f.FullName -Destination $t -Force
            $names += $rel
        }
        $line = "virtualstore: moved $($files.Count) stale file(s) of $d aside to $dest`: $($names -join ', ')"
        $out.Add($line); Log $line
    }
}
function Do-Launch([string]$route, [string]$why, $out) {
    $z = Zombie-Reason; if ($z) { return $z }
    $r = Game-Running-Reason; if ($r) { return "$r - refusing to start a second instance (close it with a kill job first)" }
    $f = Foreign-LockReason; if ($f) { return $f }
    try { Clear-VirtualStore $out } catch { return "could not move the VirtualStore copies aside: $($_.Exception.Message)" }
    if (-not $route) { $route = $A.launch_route }
    if ($route -eq 'steam') {
        if (-not $A.steam_uri) { return 'this adapter has no steam_uri' }
        Start-Process -FilePath $A.steam_uri
        $script:LaunchAt = Get-Date
        $out.Add("started $($A.steam_uri) [$why]")
        Log "launch: $why -> $($A.steam_uri)"
        $deadline = (Get-Date).AddSeconds($A.steam_wait_s)
        while ((Get-Date) -lt $deadline -and -not @(Get-GameProcs).Count) { Pump; Start-Sleep -Milliseconds 500 }
        # J2 L5: the steam route fails when no game process appears (it used to return success and only warn)
        if (-not @(Get-GameProcs).Count) { return "no $($A.game_image) process within steam_wait_s=$($A.steam_wait_s) s of $($A.steam_uri)" }
        return $null
    }
    $exe = GamePath $A.launch_exe
    if (-not (Test-Path -LiteralPath $exe)) { return "game executable not found: $exe" }
    if ($A.launch_args) { $p = Start-Process -FilePath $exe -WorkingDirectory $A.game_dir -ArgumentList $A.launch_args -PassThru }
    else { $p = Start-Process -FilePath $exe -WorkingDirectory $A.game_dir -PassThru }
    $script:LaunchAt = Get-Date
    $out.Add("started $exe (pid $($p.Id)) in $($A.game_dir) [$why]")
    Log "launch: $why -> pid $($p.Id)"
    $deadline = (Get-Date).AddSeconds((IntSet 'launch_confirm_s'))
    while ((Get-Date) -lt $deadline -and -not @(Get-GameProcs).Count) { Pump; Start-Sleep -Milliseconds 500 }
    return $null
}
# Waits (in the job's slot, pumping housekeeping) for a regex to show up in the heartbeat/proxy log written after the launch.
function Wait-LogLine([string]$rx, [int]$secs, $out) {
    $deadline = (Get-Date).AddSeconds($secs)
    $since = $LaunchAt; if (-not $since) { $since = Get-Date }
    while ((Get-Date) -lt $deadline) {
        Pump
        if (-not @(Get-GameProcs).Count) { $out.Add("wait_log: the game exited before '$rx' appeared"); return $false }
        foreach ($f in $A.heartbeat_files) {
            $p = GamePath $f
            if (-not (Test-Path -LiteralPath $p)) { continue }
            if ((Get-Item -LiteralPath $p).LastWriteTime -lt $since.AddSeconds(-2)) { continue }
            try {
                $txt = $Latin1.GetString((Read-Shared $p))
                $m = [regex]::Match($txt, "(?m)^.*(?:$rx).*$")
                if ($m.Success) { $out.Add("reached after $([int]((Get-Date) - $since).TotalSeconds) s: $($m.Value.Trim())"); return $true }
            } catch { }
        }
        Start-Sleep -Milliseconds 500
    }
    $out.Add("wait_log: '$rx' not seen within $secs s")
    return $false
}

# ------------------------------------------------------------------------------------------------ profiles ----------
function Get-Active { if (Test-Path -LiteralPath $ActivePath) { try { return ([IO.File]::ReadAllText($ActivePath, $Utf8) | ConvertFrom-Json) } catch { } }; return $null }
function Detect-Enc([byte[]]$b) {
    if ($b.Length -ge 2 -and $b[0] -eq 0xFF -and $b[1] -eq 0xFE) { return @{ name = 'utf16le'; bom = 2; enc = (New-Object Text.UnicodeEncoding($false, $false)); preamble = [byte[]]@(0xFF, 0xFE) } }
    if ($b.Length -ge 2 -and $b[0] -eq 0xFE -and $b[1] -eq 0xFF) { return @{ name = 'utf16be'; bom = 2; enc = (New-Object Text.UnicodeEncoding($true, $false)); preamble = [byte[]]@(0xFE, 0xFF) } }
    if ($b.Length -ge 3 -and $b[0] -eq 0xEF -and $b[1] -eq 0xBB -and $b[2] -eq 0xBF) { return @{ name = 'utf8bom'; bom = 3; enc = $Latin1; preamble = [byte[]]@(0xEF, 0xBB, 0xBF) } }
    return @{ name = 'latin1'; bom = 0; enc = $Latin1; preamble = [byte[]]@() }
}
# Overlay style 'prefs': the game's own preferences.script.txt, UTF-16LE with BOM, CRLF lines `key value; # key <type>, description #`.
# An existing key's VALUE is replaced in place (its comment and every other byte stay identical); a missing key is appended as `key value;`.
# Set lines are `key value` or `key=value`; '!key' is refused. An empty base becomes a new UTF-16LE file with a BOM.
function Apply-PrefsOverlay([byte[]]$bytes, [string]$setText) {
    if ($bytes.Length -eq 0) { $e = Detect-Enc ([byte[]]@(0xFF, 0xFE)); $text = '' }
    else { $e = Detect-Enc $bytes; $text = $e.enc.GetString($bytes, $e.bom, $bytes.Length - $e.bom) }
    if ($e.name -ne 'utf16le') { throw "overlay: style prefs needs a UTF-16LE file with a BOM (this one is $($e.name))" }
    $nl = "`r`n"; if ($text.Length -gt 0 -and -not $text.Contains("`r`n") -and $text.Contains("`n")) { $nl = "`n" }
    foreach ($raw in ($setText -split "`r?`n")) {
        $s = $raw.Trim()
        if (-not $s -or $s.StartsWith('#')) { continue }
        if ($s.StartsWith('!')) { throw "overlay: '!key' is not supported for style prefs ($s)" }
        $m = [regex]::Match($s, '^([A-Za-z_][\w.\-]*)\s*[=\s]\s*(.*?)\s*;?$')
        if (-not $m.Success) { throw "overlay: '$s' is not 'key value' for a prefs file" }
        $key = $m.Groups[1].Value; $val = $m.Groups[2].Value
        $rx = New-Object Text.RegularExpressions.Regex ('(?m)^(' + [regex]::Escape($key) + '[ \t]+)([^;\r\n]*)(?=;)')
        if ($rx.IsMatch($text)) {
            $ev = [Text.RegularExpressions.MatchEvaluator]{ param($mm) $mm.Groups[1].Value + $val }
            $text = $rx.Replace($text, $ev, 1)
        } else {
            if ($text.Length -gt 0 -and -not $text.EndsWith("`n")) { $text += $nl }
            $text += "$key $val;" + $nl
        }
    }
    $enc = $e.enc.GetBytes($text)
    $res = New-Object byte[] ($e.preamble.Length + $enc.Length)
    [Array]::Copy($e.preamble, 0, $res, 0, $e.preamble.Length)
    [Array]::Copy($enc, 0, $res, $e.preamble.Length, $enc.Length)
    return ,$res
}
# One value from a prefs file's bytes ($null when the key or the file is absent).
function Get-PrefsValue([byte[]]$bytes, [string]$key) {
    if ($null -eq $bytes -or $bytes.Length -lt 2) { return $null }
    $e = Detect-Enc $bytes
    $text = $e.enc.GetString($bytes, $e.bom, $bytes.Length - $e.bom)
    $m = [regex]::Match($text, '(?m)^' + [regex]::Escape($key) + '[ \t]+([^;\r\n]*?)\s*;')
    if ($m.Success) { return $m.Groups[1].Value }
    return $null
}
# Key overlay on a text file, byte-transparent (BOM and encoding kept; 8-bit text goes through Latin-1 so UTF-8 content survives).
#   style 'ini' : keys are section.key=value (section compared case-insensitively), comment char ';', written key=value
#   style 'conf': keys are the whole name (DXVK keys contain dots), comment char '#', written key = value
#   '!key' comments the key out. An existing key's first line is replaced, later duplicates are commented out, a missing key is added
#   at the end of its section (ini; the section is created if needed) or at the end of the file (conf).
function Apply-Overlay([byte[]]$bytes, [string]$setText, [string]$style, [string]$profile) {
    if ($style -eq 'prefs') { return ,(Apply-PrefsOverlay $bytes $setText) }
    if ($style -ne 'ini' -and $style -ne 'conf') { throw "overlay: this target has style '$style'; only a full copy can be installed" }
    $e = Detect-Enc $bytes
    $text = $e.enc.GetString($bytes, $e.bom, $bytes.Length - $e.bom)
    $nl = "`r`n"; if ($text.Length -gt 0 -and -not $text.Contains("`r`n") -and $text.Contains("`n")) { $nl = "`n" }
    $lines = New-Object Collections.Generic.List[string]
    foreach ($l in ($text -split "`r?`n")) { $lines.Add($l) }
    if ($lines.Count -and $lines[$lines.Count - 1] -eq '' -and $text.EndsWith("`n")) { $lines.RemoveAt($lines.Count - 1) }
    if ($text.Length -eq 0) { $lines.Clear() }
    $cc = if ($style -eq 'ini') { ';' } else { '#' }
    $sep = if ($style -eq 'ini') { '=' } else { ' = ' }
    foreach ($raw in ($setText -split "`r?`n")) {
        $s = $raw.Trim()
        if (-not $s -or $s.StartsWith('#') -or $s.StartsWith(';')) { continue }
        $remove = $s.StartsWith('!'); if ($remove) { $s = $s.Substring(1).Trim() }
        $kv = $s -split '=', 2
        $full = $kv[0].Trim(); $val = if ($kv.Count -gt 1) { $kv[1].Trim() } else { '' }
        $sec = ''; $key = $full
        if ($style -eq 'ini') {
            if ($full -notmatch '^([^.\s]+)\.(.+)$') { throw "overlay: '$full' must be section.key for an ini file" }
            $sec = $Matches[1].ToLower(); $key = $Matches[2]
        }
        $cur = ''; $done = $false; $lastInSec = -1; $secFound = ($style -ne 'ini')
        for ($i = 0; $i -lt $lines.Count; $i++) {
            $t = $lines[$i].Trim()
            if ($style -eq 'ini' -and $t.StartsWith('[') -and $t.Contains(']')) { $cur = $t.Substring(1, $t.IndexOf(']') - 1).Trim().ToLower(); if ($cur -eq $sec) { $secFound = $true; $lastInSec = $i }; continue }
            if ($cur -ne $sec -and $style -eq 'ini') { continue }
            if ($t) { $lastInSec = $i }
            if ($t.StartsWith($cc) -or $t.StartsWith('#')) { continue }
            if ($t -match ('^' + [regex]::Escape($key) + '\s*=')) {
                if ($remove -or $done) { $lines[$i] = "$cc (profile $profile) " + $lines[$i] }
                else { $lines[$i] = "$key$sep$val"; $done = $true }
            }
        }
        if (-not $done -and -not $remove) {
            if ($style -eq 'ini') {
                if (-not $secFound) { if ($lines.Count) { $lines.Add('') }; $lines.Add("[$sec]"); $lines.Add("$key$sep$val") }
                else { $lines.Insert($lastInSec + 1, "$key$sep$val") }
            } else { $lines.Add("$key$sep$val") }
        }
    }
    $body = ($lines -join $nl)
    if ($lines.Count) { $body += $nl }
    $enc = $e.enc.GetBytes($body)
    $res = New-Object byte[] ($e.preamble.Length + $enc.Length)
    [Array]::Copy($e.preamble, 0, $res, 0, $e.preamble.Length)
    [Array]::Copy($enc, 0, $res, $e.preamble.Length, $enc.Length)
    return ,$res
}
function Resolve-Req([string]$spec) {
    # 'game:rel' | 'appdata:rel' | a config-file id
    if ($spec -match '^(game|appdata):(.+)$') { return (Join-Path $(if ($Matches[1] -eq 'game') { $A.game_dir } else { $A.appdata_dir }) $Matches[2]) }
    foreach ($t in $A.config_files) { if ($t.id -eq $spec) { return (Target-Path $t) } }
    return $null
}
function Take-Snapshot([string]$owner, $out) {
    $snapName = "$(UtcStamp (Get-Date))_$($owner -replace '[^\w.\-]', '_')"
    $snapDir = Join-Path $SavedDir $snapName
    New-Item -ItemType Directory -Path (Join-Path $snapDir 'files') -Force | Out-Null
    $files = @()
    foreach ($t in $A.config_files) {
        $abs = Target-Path $t
        $e = [ordered]@{ id = $t.id; path = $abs; existed = $false; sha256 = $null; bytes = $null }
        if (Test-Path -LiteralPath $abs) {
            $dst = Join-Path (Join-Path $snapDir 'files') $t.id
            Copy-Item -LiteralPath $abs -Destination $dst -Force
            $e.existed = $true; $e.sha256 = Sha $abs; $e.bytes = (Get-Item -LiteralPath $abs -Force).Length   # -Force: hidden files (.sp_default.battle_preferences) are invisible to Get-Item without it
            if ((Sha $dst) -ne $e.sha256) { throw "snapshot copy of $($t.id) does not match the original (file changed while copying?)" }
        }
        $files += [pscustomobject]$e
    }
    $manifest = [pscustomobject]@{ owner = $owner; created_utc = (UtcStr (Get-Date)); files = $files }
    Write-Atomic (Join-Path $snapDir 'manifest.json') ($manifest | ConvertTo-Json -Depth 5)
    $out.Add("snapshot: profiles\_saved\$snapName ($(@($files | Where-Object { $_.existed }).Count) of $($files.Count) config files exist; absent is recorded too)")
    return $snapName
}
function Restore-Snapshot([string]$snapDir, $out) {
    $manifest = [IO.File]::ReadAllText((Join-Path $snapDir 'manifest.json'), $Utf8) | ConvertFrom-Json
    $bad = 0
    foreach ($f in @($manifest.files)) {
        $t = $A.config_files | Where-Object { $_.id -eq $f.id } | Select-Object -First 1
        if (-not $t) { continue }
        $abs = Target-Path $t
        if ($f.existed) {
            if ((Test-Path -LiteralPath $abs) -and (Sha $abs) -eq $f.sha256) { if ($null -ne $out) { $out.Add("restored $($f.id)  sha256 $($f.sha256.Substring(0, 12)) OK (unchanged)") }; continue }
            $src = Join-Path (Join-Path $snapDir 'files') $f.id
            if ((Sha $src) -ne $f.sha256) { $bad++; if ($null -ne $out) { $out.Add("restore $($f.id): the saved copy itself no longer matches its sha256") }; continue }
            $dir = Split-Path $abs; if (-not (Test-Path -LiteralPath $dir)) { New-Item -ItemType Directory -Path $dir -Force | Out-Null }
            $tmp = "$abs.wtmp"
            try { Copy-Item -LiteralPath $src -Destination $tmp -Force; Move-Into $tmp $abs } finally { Remove-Quiet $tmp }
            $h = Sha $abs
            $ok = ($h -eq $f.sha256); if (-not $ok) { $bad++ }
            if ($null -ne $out) { $out.Add("restored $($f.id)  sha256 $($h.Substring(0, 12)) $(if ($ok) { 'OK (byte-identical)' } else { "MISMATCH, want $($f.sha256.Substring(0, 12))" })") }
        } elseif (Test-Path -LiteralPath $abs) {
            $dest = Join-Path (ToDelete "restore_$(UtcStamp (Get-Date))") "$($f.id)__$([IO.Path]::GetFileName($abs))"
            Move-Item -LiteralPath $abs -Destination $dest -Force
            if (Test-Path -LiteralPath $abs) { $bad++ }
            if ($null -ne $out) { $out.Add("restored $($f.id)  absent again (the profile's file moved to _to_delete)") }
        } elseif ($null -ne $out) { $out.Add("restored $($f.id)  absent, as recorded") }
    }
    return $bad
}
function Profile-Apply([string]$name, [string]$owner, $out) {
    if ($name -notmatch '^[A-Za-z0-9][A-Za-z0-9._\-]*$' -or $name.StartsWith('_')) { return "bad profile name '$name'" }
    $dir = Join-Path $ProfilesDir $name
    if (-not (Test-Path -LiteralPath $dir)) {
        $have = @(Get-ChildItem -LiteralPath $ProfilesDir -Directory | Where-Object { -not $_.Name.StartsWith('_') } | ForEach-Object { $_.Name }) -join ', '
        return "no profile '$name' (have: $have)"
    }
    $r = Game-Running-Reason; if ($r) { return "game is $r - configs are switched only while it is closed" }
    $active = Get-Active
    if ($active -and $active.owner -ne $owner) { return "profile '$($active.name)' of owner '$($active.owner)' is still active (its restore is pending); try again in a few seconds" }
    $meta = $null
    $mf = Join-Path $dir 'profile.json'
    if (Test-Path -LiteralPath $mf) { try { $meta = [IO.File]::ReadAllText($mf, $Utf8) | ConvertFrom-Json } catch { return "profile '$name': profile.json does not parse: $($_.Exception.Message)" } }
    if ($meta) { foreach ($rq in @($meta.requires)) { if ($rq) { $pp = Resolve-Req ([string]$rq); if (-not $pp -or -not (Test-Path -LiteralPath $pp)) { return "profile '$name' requires $rq, which is not on the PC" } } } }
    $snapDir = $null
    if ($active) { $snapDir = Join-Path $SavedDir $active.snapshot }
    # plan first, nothing touched yet. With a profile already active, overlays are computed on the SNAPSHOT base, so profiles never stack.
    $plan = [ordered]@{}
    foreach ($t in $A.config_files) {
        $full = Join-Path $dir $t.id; $set = "$full.set"; $abn = "$full.absent"
        $kinds = @(@($full, $set, $abn) | Where-Object { Test-Path -LiteralPath $_ })
        if ($kinds.Count -gt 1) { return "profile '$name' has more than one of '$($t.id)', '$($t.id).set', '$($t.id).absent'" }
        if (-not $kinds.Count) { continue }
        if (Test-Path -LiteralPath $full) { $plan[$t.id] = @{ kind = 'copy'; bytes = [IO.File]::ReadAllBytes($full); t = $t } }
        elseif (Test-Path -LiteralPath $abn) { $plan[$t.id] = @{ kind = 'absent'; bytes = $null; t = $t } }
        else {
            $base = [byte[]]@()
            if ($snapDir) { $sp = Join-Path (Join-Path $snapDir 'files') $t.id; if (Test-Path -LiteralPath $sp) { $base = [IO.File]::ReadAllBytes($sp) } }
            else { $ab = Target-Path $t; if (Test-Path -LiteralPath $ab) { $base = [IO.File]::ReadAllBytes($ab) } }
            try { $nb = Apply-Overlay $base ($Latin1.GetString([IO.File]::ReadAllBytes($set))) $t.style $name } catch { return "profile '$name': $($t.id): $($_.Exception.Message)" }
            $plan[$t.id] = @{ kind = 'overlay'; bytes = [byte[]]$nb; t = $t }
        }
    }
    if (-not $plan.Count) { return "profile '$name' contains none of the config files ($((@($A.config_files | ForEach-Object { $_.id })) -join ', ')), their .set overlays or .absent markers" }
    if ($meta) { foreach ($w in @($meta.warn_missing)) { if ($w) { $pp = Resolve-Req ([string]$w); if (-not $pp -or -not (Test-Path -LiteralPath $pp)) { $out.Add("WARNING: $w is not on the PC; the profile's files are installed but the game runs without what they configure") } } } }
    if ($active) {
        $bad = Restore-Snapshot $snapDir $null
        if ($bad) { return "could not return to the snapshot before switching ($bad mismatches) - run 'profile restore'" }
        $out.Add("returned to the snapshot base (was: $($active.name))")
        $active.name = $name; $active.history = @($active.history) + $name
    } else {
        $sn = Take-Snapshot $owner $out
        $active = [pscustomobject]@{ name = $name; owner = $owner; snapshot = $sn; applied_utc = (UtcStr (Get-Date)); history = @($name) }
    }
    Write-Atomic $ActivePath ($active | ConvertTo-Json -Depth 5)      # recorded BEFORE the first change: a crash mid-way can still be restored
    foreach ($id in $plan.Keys) {
        $p = $plan[$id]; $abs = Target-Path $p.t
        $before = if (Test-Path -LiteralPath $abs) { (Sha $abs).Substring(0, 12) } else { '(absent)' }
        if ($p.kind -eq 'absent') {
            if (Test-Path -LiteralPath $abs) { Move-Item -LiteralPath $abs -Destination (Join-Path (ToDelete "profile_$(UtcStamp (Get-Date))") "$id`__$([IO.Path]::GetFileName($abs))") -Force }
            $out.Add("absent  $id  $before -> (absent)")
            continue
        }
        $dirp = Split-Path $abs; if (-not (Test-Path -LiteralPath $dirp)) { New-Item -ItemType Directory -Path $dirp -Force | Out-Null }
        $tmp = "$abs.wtmp"
        try { [IO.File]::WriteAllBytes($tmp, [byte[]]$p.bytes); Move-Into $tmp $abs } finally { Remove-Quiet $tmp }
        if ((Sha $abs) -ne (Sha-Bytes ([byte[]]$p.bytes))) { return "write of $id does not verify" }
        $out.Add("$($p.kind.PadRight(7)) $id  $before -> $((Sha $abs).Substring(0, 12))")
    }
    if ($meta -and $meta.description) { $out.Add("profile '$name': $($meta.description)") }
    Log "profile: '$name' applied for owner=$owner (snapshot $($active.snapshot))"
    return $null
}
function Profile-Restore([string]$why, $out) {
    $active = Get-Active
    if (-not $active) { $out.Add('no profile is active - nothing to restore'); return $null }
    $r = Game-Running-Reason; if ($r) { return "game is $r - restore waits until it is closed" }
    $snapDir = Join-Path $SavedDir $active.snapshot
    $bad = Restore-Snapshot $snapDir $out
    $done = [pscustomobject]@{ name = $active.name; owner = $active.owner; history = $active.history; applied_utc = $active.applied_utc; restored_utc = (UtcStr (Get-Date)); why = $why; mismatches = $bad }
    Write-Atomic (Join-Path $snapDir 'restored.json') ($done | ConvertTo-Json -Depth 5)
    if ($bad -eq 0) { Remove-Quiet $ActivePath }                      # a failed restore stays active so it is retried and reported
    Log "profile: restored the pre-'$($active.name)' configs of owner=$($active.owner) ($why), $bad mismatches"
    if ($bad) { return "$bad file(s) did not verify after restore" }
    return $null
}
# Restore by itself when the owner's lock is released, expires or changes owner: at once if the game is closed, else when it exits.
function Auto-Restore {
    $active = Get-Active
    if (-not $active) { $script:PendingRestoreLogged = $false; return }
    $l = Get-Lock
    # a lock file that exists but reads empty or unreadable is mid-rewrite (WriteAllText truncates first): decide on the next pass,
    # or a lock handed to a new owner is misread as released (J2 CI round 6, run 40787404204)
    if (-not $l -and (Test-Path -LiteralPath (RootPath 'game.lock'))) { return }
    $reason = $null
    if (-not $l) { $reason = "game.lock of owner=$($active.owner) was released or expired" }
    elseif ($l.stale) { return }                                      # expired on the next pass, then restored
    elseif ($l.owner -ne $active.owner) { $reason = "game.lock now belongs to '$($l.owner)'" }
    if (-not $reason) { return }
    if (Game-Running-Reason) {
        if (-not $PendingRestoreLogged) { Log "profile: auto-restore of '$($active.name)' (owner=$($active.owner)) pending: $reason, but the game is still running"; $script:PendingRestoreLogged = $true }
        return
    }
    $o = New-Object Collections.Generic.List[string]
    $err = Profile-Restore "auto: $reason" $o
    Log "profile: AUTO-RESTORE under owner=$($active.owner) of '$($active.name)' ($reason): $($o -join ' | ')$(if ($err) { " ERROR: $err" })"
}

# ------------------------------------------------------------------------------------------------ headless -----------
# Headless is the default for every launch (visible=1 opts out): the game's window must land on the virtual display, fail closed.
# The watcher's part: refuse early (no proxy support, no virtual display at the size), set the display mode, overlay the prefs and mod ini
# on top of whatever is in the files (the snapshot makes the restore byte for byte), measure the launch (win_probe.ps1), wait for the
# proxy's headless_status.json, kill the game if it does not report on_virtual. Details: harness/README.md.
function Tool-Summary($r) {
    $lines = @(($r.out -split "`r?`n") | Where-Object { $_.Trim() })
    $key = @($lines | Where-Object { $_ -match '^(VIRTUAL|MODE NOT|APPLY FAILED|REFUSED|NO UNIQUE|bad arguments|NOT OFFERED)' })
    if (-not $key.Count) { $key = @($lines | Select-Object -Last 3) }
    return ((@($key) -join ' | ') + " (display tool exit $($r.rc))")
}
# Runs the display tool as a child PowerShell; returns @{ rc; out }. Tests (test_hooks=1) can substitute the script.
function Run-VDisplay([string[]]$argList) {
    $tool = Join-Path $SrcDir 'vdisplay_probe.ps1'
    if ((IntSet 'test_hooks') -eq 1 -and $script:S['test_vdisplay_script']) { $tool = [string]$script:S['test_vdisplay_script'] }
    if (-not (Test-Path -LiteralPath $tool)) { return @{ rc = 99; out = "display tool not found: $tool" } }
    $q = (@($argList) | ForEach-Object { if ("$_" -match '[\s"]') { '"' + $_ + '"' } else { "$_" } }) -join ' '
    $pi = New-Object Diagnostics.ProcessStartInfo
    $pi.FileName = 'powershell.exe'
    $pi.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$tool`" $q"
    $pi.UseShellExecute = $false; $pi.CreateNoWindow = $true; $pi.RedirectStandardOutput = $true; $pi.RedirectStandardError = $true
    $pr = [Diagnostics.Process]::Start($pi)
    $so = $pr.StandardOutput.ReadToEndAsync(); $se = $pr.StandardError.ReadToEndAsync()
    $deadline = (Get-Date).AddSeconds(90)
    while (-not $pr.HasExited -and (Get-Date) -lt $deadline) { Pump; Start-Sleep -Milliseconds 200 }
    if (-not $pr.HasExited) { try { $pr.Kill() } catch { }; return @{ rc = 98; out = 'display tool did not finish within 90 s (killed)' } }
    $pr.WaitForExit()
    return @{ rc = $pr.ExitCode; out = ($so.Result + $se.Result) }
}
function Vd-Name { if ($A.headless -and $A.headless.display_name) { return $A.headless.display_name }; return 'Virtual Display Driver' }
# Puts the virtual display back to the mode saved before a launch changed it ($null = done or nothing to do).
function Vdisplay-Restore([string]$why) {
    $f = RootPath 'vdisplay_restore.json'
    if (-not (Test-Path -LiteralPath $f)) { return $null }
    $r = Run-VDisplay @('-Restore', $f, '-Name', (Vd-Name))
    if ($r.rc -eq 0) {
        Move-Item -LiteralPath $f -Destination (Join-Path (ToDelete '') "vdisplay_restore_$(UtcStamp (Get-Date)).json") -Force
        Log "vdisplay: previous mode restored ($why): $(Tool-Summary $r)"
        return $null
    }
    $m = "vdisplay: RESTORE FAILED ($why): $(Tool-Summary $r)"
    Log $m
    return $m
}
# Housekeeping in Pump: once the game has exited (and no job holds it), restore a mode a launch changed - after a crash or kill too.
function Vdisplay-Housekeeping {
    if (-not (Test-Path -LiteralPath (RootPath 'vdisplay_restore.json'))) { return }
    if ((Get-Date) -lt $VdRetryAt) { return }
    if (@(Get-GameProcs).Count -or ($Cur -and $Cur.holds_game)) { return }
    # once per sitting, not per launch: every mode change makes Windows move the real cursor (J13 PC run), so the mode stays while a
    # valid lock is held and is restored when the lock is released or expires
    $l = Get-Lock; if ($l -and -not $l.stale) { return }
    if (Vdisplay-Restore 'the game has exited and the lock is released') { $script:VdRetryAt = (Get-Date).AddSeconds(60) }
}
# Display step of a headless launch: -Check at the wanted size, -Set when the virtual display exists at another size. Returns @{ err; rect }.
function Headless-Display([string]$size, $out) {
    $name = Vd-Name
    $r = Run-VDisplay @('-Check', '-Size', $size, '-Name', $name)
    if ($r.rc -eq 4) {
        $out.Add("headless: the virtual display is at another size; setting $size (the mode before this lock is restored when the lock is released)")
        # the first change under a lock saves the mode to restore; a later one keeps that file and saves its own step aside
        $save = RootPath 'vdisplay_restore.json'
        if (Test-Path -LiteralPath $save) { $save = Join-Path (ToDelete 'vdisplay_steps') "$(UtcStamp (Get-Date))_$size.json" }
        $setRes = Run-VDisplay @('-Set', $size, '-SaveTo', $save, '-Name', $name)
        foreach ($l in @(($setRes.out -split "`r?`n") | Where-Object { $_.Trim() })) { $out.Add("  display tool: $l") }
        if ($setRes.rc -ne 0) { return @{ err = "headless: the virtual display cannot be put at ${size}: $(Tool-Summary $setRes). Use a size the driver offers, or visible=1 with Liam present"; rect = $null } }
        $r = Run-VDisplay @('-Check', '-Size', $size, '-Name', $name)
    }
    if ($r.rc -ne 0) { return @{ err = "headless: no virtual display at ${size}: $(Tool-Summary $r). Nothing was started; use visible=1 only with Liam present"; rect = $null } }
    $rect = $null
    $m = [regex]::Match($r.out, 'rect=(-?\d+),(-?\d+),(-?\d+),(-?\d+)')
    if ($m.Success) { $rect = @([int]$m.Groups[1].Value, [int]$m.Groups[2].Value, [int]$m.Groups[3].Value, [int]$m.Groups[4].Value) }
    $ok = @(($r.out -split "`r?`n") | Where-Object { $_ -match '^VIRTUAL OK' } | Select-Object -First 1)
    $out.Add("headless: $($ok -join '')")
    return @{ err = $null; rect = $rect }
}
function Headless-Expand([string]$v, [int]$W, [int]$H) { return $v.Replace('{W}', "$W").Replace('{H}', "$H") }
# Overlay step: the adapter's headless prefs and mod ini keys on top of what is in the files now. With no profile active a snapshot is taken
# and _active.json recorded exactly like a profile, so the lock-release / expiry restore returns the files byte for byte.
function Headless-Overlay([int]$W, [int]$H, [string]$owner, $rect, $out) {
    $hl = $A.headless
    $active = Get-Active
    if ($active -and $active.owner -ne $owner) { return "profile '$($active.name)' of owner '$($active.owner)' is still active (its restore is pending); try again in a few seconds" }
    $sets = [ordered]@{
        prefs   = ((@($hl.prefs.Keys | ForEach-Object { "$_ $(Headless-Expand $hl.prefs[$_] $W $H)" })) -join "`n")
        mod_ini = ((@($hl.mod_ini.Keys | ForEach-Object { "$_=$(Headless-Expand $hl.mod_ini[$_] $W $H)" })) -join "`n")
    }
    $plan = [ordered]@{}
    foreach ($id in $sets.Keys) {
        if (-not $sets[$id]) { continue }
        $t = $A.config_files | Where-Object { $_.id -eq $id } | Select-Object -First 1
        if (-not $t) { return "the adapter has no config file '$id' to overlay for headless" }
        $abs = Target-Path $t
        $base = [byte[]]@(); if (Test-Path -LiteralPath $abs) { $base = [IO.File]::ReadAllBytes($abs) }
        try { $nb = Apply-Overlay $base $sets[$id] $t.style 'headless' } catch { return "headless overlay of ${id}: $($_.Exception.Message)" }
        $plan[$id] = @{ t = $t; abs = $abs; bytes = [byte[]]$nb; changed = (-not (Test-Path -LiteralPath $abs)) -or ((Sha-Bytes $base) -ne (Sha-Bytes ([byte[]]$nb))) }
    }
    # (d) a window position inside the virtual display's rect in the user's own prefs is a leak to watch for
    $basePrefs = $null
    $pt = $A.config_files | Where-Object { $_.id -eq 'prefs' } | Select-Object -First 1
    if ($pt) {
        if ($active) { $sp = Join-Path (Join-Path (Join-Path $SavedDir $active.snapshot) 'files') 'prefs'; if (Test-Path -LiteralPath $sp) { $basePrefs = [IO.File]::ReadAllBytes($sp) } }
        elseif (Test-Path -LiteralPath (Target-Path $pt)) { $basePrefs = [IO.File]::ReadAllBytes((Target-Path $pt)) }
    }
    if ($rect -and $basePrefs) {
        $xp = Get-PrefsValue $basePrefs 'x_pos'; $yp = Get-PrefsValue $basePrefs 'y_pos'
        $xi = 0; $yi = 0
        if ([int]::TryParse("$xp", [ref]$xi) -and [int]::TryParse("$yp", [ref]$yi) -and $xi -ge $rect[0] -and $xi -lt $rect[2] -and $yi -ge $rect[1] -and $yi -lt $rect[3]) {
            $warn = "WARNING: the base preferences carry x_pos=$xi y_pos=$yi, which is INSIDE the virtual display's rect ($($rect -join ',')): a visible launch would open on the virtual display, and the game may have written it back. Check how it got there."
            $out.Add($warn); Log "headless: $warn"
        }
    }
    if ($active) {
        if (@($active.history)[-1] -ne 'headless') { $active.history = @($active.history) + 'headless' }
    } else {
        $sn = Take-Snapshot $owner $out
        $active = [pscustomobject]@{ name = 'headless'; owner = $owner; snapshot = $sn; applied_utc = (UtcStr (Get-Date)); history = @('headless') }
    }
    Write-Atomic $ActivePath ($active | ConvertTo-Json -Depth 5)      # recorded BEFORE the first change
    foreach ($id in $plan.Keys) {
        $p = $plan[$id]
        if (-not $p.changed) { $out.Add("headless: $id already carries the headless keys"); continue }
        $before = if (Test-Path -LiteralPath $p.abs) { (Sha $p.abs).Substring(0, 12) } else { '(absent)' }
        $dirp = Split-Path $p.abs; if (-not (Test-Path -LiteralPath $dirp)) { New-Item -ItemType Directory -Path $dirp -Force | Out-Null }
        $tmp = "$($p.abs).wtmp"
        try { [IO.File]::WriteAllBytes($tmp, $p.bytes); Move-Into $tmp $p.abs } finally { Remove-Quiet $tmp }
        if ((Sha $p.abs) -ne (Sha-Bytes $p.bytes)) { return "write of $id does not verify" }
        $out.Add("headless overlay $id  $before -> $((Sha $p.abs).Substring(0, 12))")
    }
    Log "headless: overlay applied for owner=$owner (snapshot $($active.snapshot)): $W x $H"
    return $null
}
# Everything a headless launch needs before the game starts. Returns an error string ('refused') or $null; @{rect} through $script:HeadlessRect.
function Headless-Prepare([string]$size, [int]$W, [int]$H, [string]$owner, $out) {
    $hl = $A.headless
    $z = Zombie-Reason; if ($z) { return $z }
    $r = Game-Running-Reason; if ($r) { return "$r - refusing to start a second instance (close it with a kill job first)" }
    $f = Foreign-LockReason; if ($f) { return $f }
    $mf = GamePath $hl.marker_file
    $has = $false
    if (Test-Path -LiteralPath $mf) { try { $has = Bytes-Contain (Read-Shared $mf) $hl.marker } catch { } }
    if (-not $has) { return "headless: $mf does not contain '$($hl.marker)', so this proxy build cannot run headless (the window would land on a real monitor). Deploy the current proxy, or use visible=1 only with Liam present" }
    $vr = RootPath 'vdisplay_restore.json'
    $l = Get-Lock
    $started = [DateTime]::MinValue
    if ($l -and $l.started) { [void][DateTime]::TryParse($l.started, $Inv, [Globalization.DateTimeStyles]::AdjustToUniversal -bor [Globalization.DateTimeStyles]::AssumeUniversal, [ref]$started) }
    if ((Test-Path -LiteralPath $vr) -and (Get-Item -LiteralPath $vr).LastWriteTimeUtc -lt $started) {   # left by an earlier lock
        $pend = Vdisplay-Restore 'before a launch under a new lock'
        if ($pend) { return "headless: an earlier display mode could not be restored yet ($pend)" }
    }
    $d = Headless-Display $size $out
    if ($d.err) { return $d.err }
    $e = Headless-Overlay $W $H $owner $d.rect $out
    if ($e) { return $e }
    return $null
}
function Bytes-Contain([byte[]]$b, [string]$ascii) { return ($Latin1.GetString($b).IndexOf($ascii, [StringComparison]::Ordinal) -ge 0) }
# Starts win_probe.ps1 detached (it samples from before the game starts until it exits); returns its folder or $null.
function Start-WinProbe($out) {
    if ((IntSet 'winprobe') -eq 0) { return $null }
    $script = Join-Path $SrcDir 'win_probe.ps1'
    if (-not (Test-Path -LiteralPath $script)) { $out.Add('WARNING: win_probe.ps1 is not next to the watcher: this launch is NOT measured'); return $null }
    $rel = "runs\$(UtcStamp (Get-Date))_winprobe"
    $dir = RootPath $rel
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    $cl = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -OutDir `"$dir`" -Image `"$($A.game_image)`" -VirtualName `"$(Vd-Name)`" -WaitStartS 240"
    $r = Start-Detached $cl $dir
    $deadline = (Get-Date).AddSeconds(30)
    while ((Get-Date) -lt $deadline -and -not (Test-Path -LiteralPath (Join-Path $dir 'ready.txt'))) { Pump; Start-Sleep -Milliseconds 200 }
    if (Test-Path -LiteralPath (Join-Path $dir 'ready.txt')) { $out.Add("window probe: $rel (pid $($r.ProcessId)); winprobe.json and winprobe.txt when the game exits") }
    else { $out.Add("WARNING: the window probe in $rel did not report ready within 30 s; the launch goes ahead") }
    return $dir
}
# Waits for the proxy's status file to name this pid on_virtual (ok) or refused; anything else in time is fail closed (the game is killed).
function Headless-Wait([int]$waitS, $out) {
    $hl = $A.headless
    $sp = GamePath $hl.status_file
    $g = @(Get-GameProcs)
    if (-not $g.Count) { return "HEADLESS FAILED: $($A.game_image) is not running after the start (exit code $($hl.exit_code) = the proxy refused; read $($hl.status_file))" }
    $gpid = $g[0].Id
    $deadline = (Get-Date).AddSeconds($waitS)
    $last = '(no status yet)'
    while ((Get-Date) -lt $deadline) {
        Pump
        $st = $null; if (Test-Path -LiteralPath $sp) { $st = Read-JsonRetry $sp 3 }
        if ($st -and [int]$st.pid -eq $gpid) {
            $line = "$($st.state) $($st.detail)".Trim()
            if ($line -ne $last) { $last = $line; $out.Add("headless status: $line") }
            if ($st.state -eq 'on_virtual') {
                $tg = if ($st.target) { "$($st.target.device) rect $(@($st.target.rect) -join ',')" } else { '?' }
                $out.Add("headless: on_virtual (target $tg, window $(@($st.window) -join 'x'), client $(@($st.client) -join 'x'), back buffer $(@($st.backbuffer) -join 'x'))")
                return $null
            }
            if ($st.state -eq 'refused') {
                if (Get-Process -Id $gpid -ErrorAction SilentlyContinue) { [void](Kill-Game 'headless refused' $out) }
                return "HEADLESS FAILED: the proxy refused the launch: $($st.detail) (exit code $($st.exit_code); nothing was shown on a real monitor)"
            }
        }
        if (-not (Get-Process -Id $gpid -ErrorAction SilentlyContinue)) { return "HEADLESS FAILED: the game exited before reporting on_virtual (last status: $last)" }
        Start-Sleep -Milliseconds 250
    }
    [void](Kill-Game 'headless status timeout' $out)
    return "HEADLESS FAILED: no on_virtual status for pid $gpid within $waitS s (last: $last); the game was killed (fail closed)"
}
# The launch job. Headless unless visible=1 (or the adapter has no headless block).
function Launch-Job($hdr, $c, $o) {
    $err = Exe-Gate $o; if ($err) { return $err }   # before any display or config change
    $headless = ($A.headless -and $hdr['visible'] -ne '1')
    $W = 0; $H = 0
    if ($headless) {
        $size = $A.headless.default_size; if ($hdr['size']) { $size = $hdr['size'] }
        $m = [regex]::Match("$size", '^(\d{3,5})x(\d{3,5})$')
        if (-not $m.Success) { return "bad size '$size': want WxH, for example 3840x2160" }
        $W = [int]$m.Groups[1].Value; $H = [int]$m.Groups[2].Value
        $err = Headless-Prepare $size $W $H $c.owner $o
        if ($err) { return $err }
    } else { $o.Add('visible launch: no config touched, no display checked; the window goes wherever the game puts it (only for sittings with Liam present)') }
    $probeDir = Start-WinProbe $o
    $err = Do-Launch $hdr['route'] "launch job $($c.id) owner=$($c.owner)$(if ($headless) { " headless ${W}x${H}" } else { ' visible' })" $o
    if ($err) { if ($probeDir) { [IO.File]::WriteAllText((Join-Path $probeDir 'stop'), 'stop', $Utf8) }; return $err }
    $g = @(Get-GameProcs)
    if ($g.Count) { $o.Add("running: $($A.game_image) pid $($g[0].Id)") } else { $o.Add("WARNING: $($A.game_image) not seen in the process list after the start (it may have exited at once)") }
    if ($headless) {
        $ws = 180; if ($hdr['headless_wait_s']) { $ws = [int]$hdr['headless_wait_s'] }
        $err = Headless-Wait $ws $o
        if ($err) { return $err }
    }
    if ($hdr['wait_log']) { $ws = 120; if ($hdr['wait_s']) { $ws = [int]$hdr['wait_s'] }; if (-not (Wait-LogLine $hdr['wait_log'] $ws $o)) { return "launch: the log line '$($hdr['wait_log'])' did not appear" } }
    return $null
}

# ------------------------------------------------------------------------------------------------ watchdog ----------
# A pure decision, so it can be tested without a game. $f: armed, off, since_start_s, window (none|visible|minimized|hidden|not_responding),
# window_hung_s, cpu_idle_s, log_idle_s ($null = no heartbeat file configured), hang_s, startup_s, hung_window_s, holds_game.
function Get-HangVerdict($f) {
    $no = { param($why) [pscustomobject]@{ hung = $false; why = $why } }
    if ($f.off -or -not $f.armed) { return (& $no 'not armed') }
    if ($f.since_start_s -lt $f.startup_s) { return (& $no 'start-up grace period') }
    if ($f.window -eq 'minimized' -or $f.window -eq 'hidden') { return (& $no 'window minimised or hidden (a tabbed-out game does not present)') }
    if ($f.holds_game) { return (& $no 'a launch/kill job is handling the game') }
    if ($f.window -eq 'not_responding' -and $f.window_hung_s -ge $f.hung_window_s) {
        return [pscustomobject]@{ hung = $true; why = "IsHungAppWindow for $([int]$f.window_hung_s) s (limit $($f.hung_window_s))" }
    }
    $logQuiet = ($null -eq $f.log_idle_s) -or ($f.log_idle_s -ge $f.hang_s)
    if ($f.cpu_idle_s -ge $f.hang_s -and $logQuiet) {
        return [pscustomobject]@{ hung = $true; why = "no CPU-time progress for $([int]$f.cpu_idle_s) s and no heartbeat-file write for $(if ($null -eq $f.log_idle_s) { 'n/a' } else { [int]$f.log_idle_s }) s (limit $($f.hang_s))" }
    }
    return (& $no 'alive')
}
function Heartbeat-Newest($since) {
    $best = $null
    foreach ($f in $A.heartbeat_files) {
        $p = GamePath $f
        if (Test-Path -LiteralPath $p) { $t = (Get-Item -LiteralPath $p).LastWriteTime; if ($null -eq $best -or $t -gt $best) { $best = $t } }
    }
    if ($null -eq $best -or $best -lt $since) { $best = $since }   # no file yet (or only an older one): the game has written nothing since it started
    return $best
}
function Window-State($p) {
    try {
        $p.Refresh()
        $h = $p.MainWindowHandle
        if ($h -ne [IntPtr]::Zero) {
            if ([WP.U]::IsHungAppWindow($h)) { return 'not_responding' }
            if ([WP.U]::IsIconic($h)) { return 'minimized' }
            if ([WP.U]::IsWindowVisible($h)) { return 'visible' }
            return 'hidden'
        }
    } catch { }
    return 'none'
}
# The zombie is gone when its pid is free OR now belongs to another image: pids are reused, and the flag is persisted across the
# reboot it asks for, so a bare pid check could refuse launches for ever (J2 review, 2026-10-29).
function Zombie-Gone($z, $proc) {
    if (-not $proc) { return $true }
    return ("$($proc.ProcessName).exe" -ne [string]$z.image)
}
function Watchdog {
    $g = @(Get-GameProcs)
    if ($Zombie) {
        $still = Get-Process -Id $Zombie.pid -ErrorAction SilentlyContinue
        if (Zombie-Gone $Zombie $still) { Log "zombie pid $($Zombie.pid) ($($Zombie.image)) is gone$(if ($still) { " (pid now $($still.ProcessName).exe)" }) - launches allowed again"; $script:Zombie = $null; Remove-Quiet $ZombiePath }
        else { $script:Game.state = 'zombie' }
    }
    if (-not $g.Count) {
        if (-not $Zombie) { $script:Game.state = 'not_running' }
        $script:Game.pid = $null; $script:Game.window = $null; $script:Game.cpu_idle_s = $null; $script:Game.log_idle_s = $null; $script:Game.armed = $false
        $script:Track = @{ pid = 0; cpu = $null; cpu_at = $null; hung_since = $null }
        return
    }
    if ($Zombie -and $g[0].Id -eq $Zombie.pid) { return }
    $p = $g[0]
    $start = $null; try { $start = $p.StartTime } catch { }
    if ($null -eq $start) { $start = Get-Date }
    $now = Get-Date
    if ($Track.pid -ne $p.Id) { $script:Track = @{ pid = $p.Id; cpu = $null; cpu_at = $now; hung_since = $null } }
    $cpu = $null; try { $cpu = $p.TotalProcessorTime.TotalSeconds } catch { }
    if ($null -eq $cpu) { $script:Track.cpu_at = $now }               # CPU time unreadable: cannot judge, never call it a hang from CPU alone
    elseif ($null -eq $Track.cpu -or ($cpu - $Track.cpu) -gt (NumSet 'cpu_epsilon_s')) { $script:Track.cpu_at = $now }
    $script:Track.cpu = $cpu
    $win = Window-State $p
    if ($win -eq 'not_responding') { if ($null -eq $Track.hung_since) { $script:Track.hung_since = $now } } else { $script:Track.hung_since = $null }
    $logIdle = $null
    if ($A.heartbeat_files.Count) { $logIdle = ($now - (Heartbeat-Newest $start)).TotalSeconds }
    $l = Get-Lock
    $armed = (($l -and -not $l.stale) -or ($LaunchAt -and $start -ge $LaunchAt.AddSeconds(-15)))
    $hang = IntSet 'hang_s'; if ($l -and $l.hang_s) { $hang = [int]$l.hang_s }
    $off = ((IntSet 'watchdog') -eq 0) -or (Test-Path -LiteralPath (RootPath 'watchdog.off')) -or $hang -le 0
    $facts = @{
        armed = [bool]$armed; off = [bool]$off; since_start_s = ($now - $start).TotalSeconds; window = $win
        window_hung_s = $(if ($Track.hung_since) { ($now - $Track.hung_since).TotalSeconds } else { 0 }); cpu_idle_s = ($now - $Track.cpu_at).TotalSeconds
        log_idle_s = $logIdle; hang_s = $hang; startup_s = (IntSet 'hang_startup_s'); hung_window_s = (IntSet 'hung_window_s')
        holds_game = [bool]($Cur -and $Cur.holds_game)
    }
    $script:Game.pid = $p.Id; $script:Game.window = $win; $script:Game.armed = [bool]$armed
    $script:Game.cpu_idle_s = [int]$facts.cpu_idle_s; $script:Game.log_idle_s = $(if ($null -ne $logIdle) { [int]$logIdle } else { $null })
    $script:Game.state = 'running'
    $v = Get-HangVerdict $facts
    if ($v.hung) { Handle-Hang $p $start $v.why $win }
}
function Invoke-MiniDump([int]$procId, [string]$outFile) {
    # Out of process, from the watcher: the dump is written by a child PowerShell of the TARGET's bitness (a 64-bit dbghelp cannot
    # produce a usable dump of a 32-bit WoW64 process). The first consumer's game is 32-bit.
    $script = Join-Path $SrcDir 'dump.ps1'
    if (-not (Test-Path -LiteralPath $script)) { return "dump.ps1 not found next to the watcher ($script)" }
    $ps = Join-Path $env:windir 'System32\WindowsPowerShell\v1.0\powershell.exe'
    $wow = Join-Path $env:windir 'SysWOW64\WindowsPowerShell\v1.0\powershell.exe'
    try {
        $is32 = $false
        $tp = Get-Process -Id $procId -ErrorAction Stop
        $is32 = -not (Test-Process-64 $tp)
        if ($is32 -and [Environment]::Is64BitOperatingSystem -and (Test-Path -LiteralPath $wow)) { $ps = $wow }
    } catch { }
    $pi = New-Object Diagnostics.ProcessStartInfo
    $pi.FileName = $ps
    $pi.Arguments = "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$script`" -ProcessId $procId -Out `"$outFile`" -Type $($S.dump_type)"
    $pi.UseShellExecute = $false; $pi.CreateNoWindow = $true; $pi.RedirectStandardOutput = $true; $pi.RedirectStandardError = $true
    $pr = [Diagnostics.Process]::Start($pi)
    $deadline = (Get-Date).AddSeconds((IntSet 'dump_wait_s'))
    while (-not $pr.HasExited -and (Get-Date) -lt $deadline) { Pump; Start-Sleep -Milliseconds 300 }
    if (-not $pr.HasExited) { try { $pr.Kill() } catch { }; return "minidump did not finish within $($S.dump_wait_s) s" }
    $o = $pr.StandardOutput.ReadToEnd().Trim()
    if ($pr.ExitCode -ne 0) { return "minidump failed (exit $($pr.ExitCode)): $o $($pr.StandardError.ReadToEnd().Trim())" }
    return $null
}
function Test-Process-64($proc) {
    if (-not ('WP.W' -as [type])) { Add-Type -Namespace WP -Name W -MemberDefinition '[DllImport("kernel32.dll")] public static extern bool IsWow64Process(IntPtr h, out bool wow);' }
    if (-not [Environment]::Is64BitOperatingSystem) { return $false }
    $wow = $false
    [void][WP.W]::IsWow64Process($proc.Handle, [ref]$wow)
    return (-not $wow)
}
function Handle-Hang($p, $start, [string]$why, [string]$win) {
    $script:Game.state = 'hung'
    $ts = UtcStamp (Get-Date)
    $dir = RootPath (Join-Path 'runs' "${ts}_hang")
    New-Item -ItemType Directory -Path $dir -Force | Out-Null
    Log "HANG: $($A.game_image) pid $($p.Id): $why, window=$win - archiving to runs\${ts}_hang, then taskkill /F /T"
    $notes = New-Object Collections.Generic.List[string]
    $notes.Add("hang detected $(UtcStr (Get-Date)) by watcher $Version`: pid $($p.Id) started $(UtcStr $start), $why, window=$win")
    $l = Get-Lock; if ($l) { $notes.Add("game.lock: owner=$($l.owner) purpose=$($l.purpose) age=$($l.age_s)s") }
    $dumpFile = Join-Path $dir "$($A.game_image).$($p.Id).dmp"
    $derr = Invoke-MiniDump $p.Id $dumpFile
    if ($derr) { $notes.Add("minidump: $derr") } else { $notes.Add("minidump: $([IO.Path]::GetFileName($dumpFile)) ($((Get-Item -LiteralPath $dumpFile).Length) bytes)") }
    # archive: heartbeat/proxy logs, configs, the lock, status, and any dump the game or proxy wrote since the start
    $copy = @()
    foreach ($f in (@($A.heartbeat_files) + @($A.archive_files))) { $copy += $f }
    foreach ($rel in $copy) { $src = GamePath $rel; if (Test-Path -LiteralPath $src) { try { [IO.File]::WriteAllBytes((Join-Path $dir ($rel -replace '[\\/]', '__')), (Read-Shared $src)) } catch { } } }
    foreach ($d in $A.archive_dirs_log) {
        $dd = GamePath $d
        if (Test-Path -LiteralPath $dd) { Get-ChildItem -LiteralPath $dd -Filter *.log -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $start } | ForEach-Object { try { [IO.File]::WriteAllBytes((Join-Path $dir (($d -replace '[\\/]', '__') + '__' + $_.Name)), (Read-Shared $_.FullName)) } catch { } } }
    }
    foreach ($d in $A.archive_dirs_dump) {
        $dd = GamePath $d
        if (Test-Path -LiteralPath $dd) { Get-ChildItem -LiteralPath $dd -Filter *.dmp -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -ge $start } | ForEach-Object { Copy-Item -LiteralPath $_.FullName -Destination $dir; $notes.Add("game dump: $($_.Name)") } }
    }
    foreach ($t in $A.config_files) { $tp = Target-Path $t; if (Test-Path -LiteralPath $tp) { try { [IO.File]::WriteAllBytes((Join-Path $dir ("cfg__$($t.id)__" + [IO.Path]::GetFileName($tp))), (Read-Shared $tp)) } catch { } } }
    foreach ($f in @('game.lock', 'watcher.status')) { $src = RootPath $f; if (Test-Path -LiteralPath $src) { try { [IO.File]::WriteAllBytes((Join-Path $dir $f), (Read-Shared $src)) } catch { } } }
    $notes.Add('tasklist before kill:'); $notes.Add((& tasklist.exe /v /fi "imagename eq $($A.game_image)" 2>&1 | Out-String))
    # hang.txt goes down before the kill (a watcher stopped mid-kill still leaves evidence), then is rewritten with the result
    $hangTxt = Join-Path $dir 'hang.txt'
    Write-Atomic $hangTxt ((@($notes) + 'kill: pending') -join "`r`n")
    $ok = Kill-Game "watchdog hang, runs\${ts}_hang" $notes
    $notes.Add("kill: $(if ($ok) { 'killed' } else { 'ZOMBIE - PC needs a reboot' })")
    Write-Atomic $hangTxt ($notes -join "`r`n")
    $script:LastHang = [pscustomobject]@{ at_utc = (UtcStr (Get-Date)); pid = $p.Id; dir = "runs\${ts}_hang"; why = $why; killed = $ok }
    $script:LaunchAt = $null
    Log "HANG handled: $(if ($ok) { 'killed' } else { 'ZOMBIE - PC needs a reboot' }), evidence in runs\${ts}_hang"
}

# ------------------------------------------------------------------------------------------------ status ------------
function Write-Status {
    $l = Get-Lock
    $queue = @(Get-ChildItem -LiteralPath $JobsDir -Filter *.request -ErrorAction SilentlyContinue | Where-Object { $_.Name.EndsWith('.request') } | Sort-Object LastWriteTimeUtc, Name | ForEach-Object { $_.BaseName })
    $procs = @(Get-AllGameProcs | ForEach-Object { [ordered]@{ image = $_.image; pid = $_.pid } })
    $fl = Foreign-LockReason
    $st = [ordered]@{
        version = $Version; pid = $PID; ps_version = $PSVersionTable.PSVersion.ToString(); root = $Root; game = $A.game
        started_utc = (UtcStr $StartedAt); uptime_s = [int]((Get-Date) - $StartedAt).TotalSeconds
        heartbeat_utc = (UtcStr (Get-Date)); queue_length = $queue.Count; queue = $queue
        current_job = $(if ($Cur) { [ordered]@{ id = $Cur.id; type = $Cur.type; owner = $Cur.owner; started_utc = (UtcStr $Cur.started); running_s = [int]((Get-Date) - $Cur.started).TotalSeconds } } else { $null })
        game_state = [ordered]@{ state = $Game.state; image = $A.game_image; pid = $Game.pid; window = $Game.window; cpu_idle_s = $Game.cpu_idle_s; log_idle_s = $Game.log_idle_s; watchdog_armed = $Game.armed; hang_s = (IntSet 'hang_s') }
        processes = $procs
        lock = $(if ($l) { [ordered]@{ owner = $l.owner; session = $l.session; purpose = $l.purpose; age_s = $l.age_s; stale = $l.stale } } else { $null })
        foreign_lock = $fl
        zombie = [bool]$Zombie; needs_reboot = [bool]$Zombie; zombie_detail = $Zombie
        profile_active = (Get-Active)
        last_hang = $LastHang
        exe = $ExeState
    }
    Write-Atomic $StatusPath ($st | ConvertTo-Json -Depth 6)
}
function Write-Alive {
    [IO.File]::WriteAllText($AlivePath, "$(UtcStr (Get-Date)) watcher $Version pid=$PID`r`n", $Utf8)
    Write-Status
    $script:LastAlive = Get-Date
}
function Pump {
    # housekeeping that keeps running while a job is in the slot (also called from inside long waits). Nested calls only keep the heartbeat fresh.
    if ($PumpDepth -gt 0) {
        try { if (((Get-Date) - $LastAlive).TotalSeconds -ge 2) { Write-Alive } } catch { }
        return
    }
    $script:PumpDepth++
    try {
        $ini = RootPath 'watcher.ini'
        if ((Test-Path -LiteralPath $ini) -and (Get-Item -LiteralPath $ini).LastWriteTimeUtc -ne $IniStamp) { Load-Settings; Log 'settings: watcher.ini reloaded' }
        $l = Get-Lock
        $sig = if ($l) { "$($l.owner)|$($l.purpose)" } else { '' }
        if ($sig -ne $LockSeen) { Log "lock: $(if ($l) { "held by owner=$($l.owner) purpose=$($l.purpose)" } else { 'free' })"; $script:LockSeen = $sig }
        Expire-StaleLock
        Watchdog
        Auto-Restore
        Vdisplay-Housekeeping
        if (((Get-Date) - $LastAlive).TotalSeconds -ge 2) { Write-Alive }
    } catch { Log "housekeeping error: $($_.Exception.Message) at line $($_.InvocationInfo.ScriptLineNumber)" }
    finally { $script:PumpDepth-- }
}

# ------------------------------------------------------------------------------------------------ job runner --------
function Guard-Regexes {
    $names = @(@($A.game_image) + @($A.other_images) | ForEach-Object { [regex]::Escape((Img-Base $_)) }) -join '|'
    return @(
        "\btaskkill\b.*\b($names)\b", "\bstart\b.*\b($names)\.exe\b", "\b(Stop-Process|Start-Process|kill)\b.*\b($names)\b",
        "\bwmic\b.*\b($names)\b.*\b(terminate|delete|call)\b", 'steam://rungameid', "^\s*(&|call)\s+.*\b($names)\.exe"
    )
}
function Script-TouchesGame([string]$body) {
    $rxs = Guard-Regexes
    foreach ($line in ($body -split "`r?`n")) {
        $t = $line.Trim()
        if ($t -match '^(@?rem\b|::|#)') { continue }
        foreach ($rx in $rxs) { if ($t -match $rx) { return $t } }
    }
    return $null
}
# J18 (J5 ledger row 32: never git in a game folder): a watcher job has no reason to run git (agents have Git Bash in the repo checkout),
# so any cmd or ps1 script that runs it is refused whatever job_script_guard says.
function Script-RunsGit([string]$body) {
    foreach ($line in ($body -split "`r?`n")) {
        $t = $line.Trim()
        if ($t -match '^(@?rem\b|::|#)') { continue }
        if ($t -match '(?i)(?<![\w.-])git(\.exe)?(?![\w.-])') { return $t }
    }
    return $null
}
function Script-TouchesConfig([string]$body) {
    $leafs = @($A.config_files | ForEach-Object { [regex]::Escape([IO.Path]::GetFileName($_.path)) }) -join '|'
    foreach ($line in ($body -split "`r?`n")) {
        $t = $line.Trim()
        if ($t -match '^(@?rem\b|::|#)') { continue }
        if ($t -match "($leafs)" -and $t -match '(\b(copy|move|xcopy|robocopy|del|erase|ren|rename|(Set|Add|Out)-\w+|Copy-Item|Move-Item|Remove-Item|Rename-Item|WriteAll\w*|AppendAll\w*)\b|>)') { return $t }
    }
    return $null
}
function Start-Script([string]$kind, [string]$scriptPath, [string]$outPath, [string]$cwd) {
    $psi = New-Object Diagnostics.ProcessStartInfo
    $psi.FileName = $env:ComSpec
    if ($kind -eq 'ps1') { $inner = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$scriptPath`"" }
    else { $inner = "`"$scriptPath`"" }
    $psi.Arguments = "/d /s /c `"$inner < nul > `"$outPath`" 2>&1`""
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.WorkingDirectory = $cwd
    return [Diagnostics.Process]::Start($psi)
}
# Detached start (WMI): the new process is created by the WMI host, so it inherits none of the job's handles and is not in its tree.
function Start-Detached([string]$commandLine, [string]$cwd) {
    $si = New-CimInstance -ClassName Win32_ProcessStartup -ClientOnly -Property @{ ShowWindow = [uint16]0 }
    $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{ CommandLine = $commandLine; CurrentDirectory = $cwd; ProcessStartupInformation = $si }
    return $r
}
# A script's output goes to a unique .part file and is copied to <id>.out by the WATCHER when the script ends. Anything the script started
# inherits the redirect handle and may hold it open for hours (a game): with a fixed output file that silently broke every later job (the earlier remaster's watcher v4).
function Collect-Part($c) {
    if (-not $c.part) { return }
    $bytes = [byte[]]@()
    try { if (Test-Path -LiteralPath $c.part) { $bytes = Read-Shared $c.part } } catch { $bytes = $Latin1.GetBytes("[watcher] could not read the output ($($_.Exception.Message))`r`n") }
    if ($null -eq $bytes) { $bytes = [byte[]]@() }
    $tmp = "$($c.out).wtmp"; [IO.File]::WriteAllBytes($tmp, [byte[]]$bytes); Move-Into $tmp $c.out
    Remove-Quiet $c.part
}
function Close-Job($c, [int]$exit, [string]$status, [string]$reason) {
    # Ends the job in the slot whatever happens: collecting the output or writing the result may throw; the slot is freed regardless (finally).
    try {
        try { Collect-Part $c } catch {
            $m = "output could not be collected: $($_.Exception.Message) (line $($_.InvocationInfo.ScriptLineNumber))"
            Log "job $($c.id): $m"
            try { [IO.File]::AppendAllText($c.out, "`r`n[watcher] $m`r`n", $Utf8) } catch { Log "job $($c.id): could not write the .out either: $($_.Exception.Message)" }
        }
        if ($c.warn) { try { [IO.File]::AppendAllText($c.out, "$($c.warn)`r`n", $Utf8) } catch { } }
        try { Finish-Job $c $exit $status $reason } catch {
            Log "job $($c.id): could not write its result ($status exit=$exit): $($_.Exception.Message) (line $($_.InvocationInfo.ScriptLineNumber))"
            $d = [ordered]@{ id = $c.id; type = $c.type; owner = $c.owner; exit = $exit; status = $status; reason = "$reason [result written by the fallback path: $($_.Exception.Message)]"; start_utc = (UtcStr $c.started); end_utc = (UtcStr (Get-Date)); watcher = $Version }
            try { [IO.File]::WriteAllText($c.done, ($d | ConvertTo-Json), $Utf8) } catch { Log "job $($c.id): fallback .done failed too: $($_.Exception.Message)" }
        }
    } finally { $script:Cur = $null }
}
function New-Cur([string]$id, [string]$type, [string]$owner) {
    return @{ id = $id; type = $type; owner = $owner; started = (Get-Date); proc = $null; timeout = (IntSet 'job_timeout_s'); holds_game = $false; out = $null; done = $null; part = $null; script = $null; warn = $null; args = @() }
}
function Finish-Job($c, [int]$exit, [string]$status, [string]$reason) {
    $end = Get-Date
    if ($reason -and $status -ne 'refused') { try { [IO.File]::AppendAllText($c.out, "`r`n[watcher] ${status}: $reason`r`n", $Utf8) } catch { } }
    $d = [ordered]@{ id = $c.id; type = $c.type; owner = $c.owner; exit = $exit; status = $status; reason = $reason; start_utc = (UtcStr $c.started); end_utc = (UtcStr $end); duration_s = [Math]::Round(($end - $c.started).TotalSeconds, 1); watcher = $Version }
    Write-Atomic $c.done ($d | ConvertTo-Json)                     # the result JSON is written LAST and atomically
    if ($c.script) { Remove-Quiet $c.script }
    Log "job $($c.id) [$($c.type)$(if ($c.owner) { " owner=$($c.owner)" })] $status exit=$exit$(if ($reason) { " - $reason" })"
}
function Refuse-Job($c, [string]$reason) {
    [IO.File]::WriteAllText($c.out, "REFUSED by watcher: $reason`r`n", $Utf8)
    Finish-Job $c -2 'refused' $reason
}
function Ids-Used([string]$id) {
    if (-not (Test-Path -LiteralPath $IdsPath)) { return $false }
    try { foreach ($l in [IO.File]::ReadAllLines($IdsPath)) { if ($l.EndsWith(" $id")) { return $true } } } catch { }
    return $false
}
function Ids-Add([string]$id) { [IO.File]::AppendAllText($IdsPath, "$(UtcStr (Get-Date)) $id`r`n", $Utf8) }

function Start-NextJob {
    $f = Get-ChildItem -LiteralPath $JobsDir -Filter *.request -ErrorAction SilentlyContinue | Where-Object { $_.Name.EndsWith('.request') } | Sort-Object LastWriteTimeUtc, Name | Select-Object -First 1
    if (-not $f) { return $false }
    $id = $f.BaseName
    $taken = Join-Path $JobsDir "$id.taken"
    if (-not (Is-ValidId $id)) { try { Move-Item -LiteralPath $f.FullName -Destination (Join-Path $JobsDir "$($f.Name).rejected") -Force } catch { }; Log "job file '$($f.Name)' rejected: id must match [A-Za-z0-9][A-Za-z0-9._-]{0,119}"; return $true }
    try { Move-Item -LiteralPath $f.FullName -Destination $taken -Force -ErrorAction Stop } catch { return $false }   # writer still has it open
    $body = $Latin1.GetString([IO.File]::ReadAllBytes($taken))
    Remove-Quiet $taken
    $c = New-Cur $id 'cmd' $null
    $c.out = Join-Path $JobsDir "$id.out"; $c.done = Join-Path $JobsDir "$id.done"
    $script:Cur = $c
    # Job ids are never reused: a second request with an id seen before is refused (and ITS result replaces the old one only now,
    # when the request is picked up), so an agent can never mistake an old result for the new one.
    if (Ids-Used $id) { Refuse-Job $c "job id '$id' was already used; ids must be unique (<owner>-<utc>-<random>)"; $script:Cur = $null; return $true }
    Ids-Add $id
    Remove-Quiet $c.out; Remove-Quiet $c.done
    $hdr = @{}; $bodyLines = New-Object Collections.Generic.List[string]
    foreach ($ln in ($body -split "`r?`n")) { if ($ln -match '^\s*#job\b(.*)$') { $kv = Parse-KV $Matches[1]; foreach ($k in $kv.Keys) { $hdr[$k] = $kv[$k] } } else { $bodyLines.Add($ln) } }
    $nonEmpty = @($bodyLines | Where-Object { $_.Trim() })
    $verbs = 'launch|kill|profile|restart|update|status|noop'
    if ($nonEmpty.Count -eq 1 -and $nonEmpty[0].Trim() -match "^($verbs)(\s.*)?$") {
        $c.type = $Matches[1]; $rest = "$($Matches[2])".Trim()
        $kv = Parse-KV $rest; foreach ($k in $kv.Keys) { $hdr[$k] = $kv[$k] }
        $c.args = @($rest -split '\s+' | Where-Object { $_ -and $_ -notmatch '=' })
    } elseif ($hdr['type']) { $c.type = $hdr['type'] }
    elseif ($nonEmpty.Count -and $nonEmpty[0].Trim() -match '^#\s*ps1\b') { $c.type = 'ps1' }
    $c.owner = $hdr['owner']
    if ($hdr['timeout']) { $c.timeout = [int]$hdr['timeout'] }
    Log "job $id [$($c.type)$(if ($c.owner) { " owner=$($c.owner)" })] started"
    $o = New-Object Collections.Generic.List[string]
    switch ($c.type) {
        { $_ -in @('cmd', 'ps1') } {
            $text = $bodyLines -join "`r`n"
            $git = Script-RunsGit $text
            if ($git) { Refuse-Job $c "this script runs git ('$git'): watcher jobs never run git (J18: never git in a game folder); run git from Git Bash in the repo checkout and sync with pc_deploy.py"; $script:Cur = $null; return $true }
            $hit = Script-TouchesGame $text
            $hitc = $null; if (-not $hit) { $hitc = Script-TouchesConfig $text }
            if ($hit -or $hitc) {
                $r = Check-Owner $c.owner
                if ($r) {
                    $what = if ($hit) { "starts/kills the game ('$hit')" } else { "writes a game or mod config file ('$hitc')" }
                    if ($S.job_script_guard -eq 'refuse') { Refuse-Job $c "this script $what, so it needs '#job owner=<lock owner>': $r. Prefer the launch / kill / profile job types."; $script:Cur = $null; return $true }
                    $c.warn = "WARNING (watcher): this script $what but $r"
                }
                $c.holds_game = $true
            }
            $ext = if ($c.type -eq 'ps1') { 'ps1' } else { 'cmd' }
            $c.script = Join-Path $JobsDir "$id.run.$ext"
            if ($c.type -eq 'ps1') {
                # PowerShell 5.1 reads a script without a BOM as ANSI: a ps1 job body is UTF-8 from the shell, so it is saved WITH a BOM
                # (the one deliberate exception; every data file the watcher writes is BOM-less).
                # J13 question 1: a ps1 job whose last native or script call failed ($LASTEXITCODE) fails with that code (it used to end
                # ok exit=0); an explicit `exit N` in the body still wins, since it never reaches this line
                $u8 = $Utf8.GetString($Latin1.GetBytes($text)) + "`r`n# [watcher] the last native or script call's failure fails the job`r`nif (`$LASTEXITCODE) { exit `$LASTEXITCODE }"
                [IO.File]::WriteAllBytes($c.script, [byte[]](@(0xEF, 0xBB, 0xBF) + $Utf8.GetBytes($u8 + "`r`n")))
            } else { [IO.File]::WriteAllText($c.script, $text + "`r`n", $Latin1) }
            $c.part = Join-Path $JobsDir "$id.part"
            if ((IntSet 'test_hooks') -eq 1 -and $hdr['test'] -eq 'throw_on_start') { throw 'test hook: starting the job throws after it took the slot' }
            $c.proc = Start-Script $c.type $c.script $c.part $Root
            return $true
        }
        'noop' { [IO.File]::WriteAllText($c.out, "noop ok (watcher $Version)`r`n", $Utf8); Finish-Job $c 0 'ok' $null; $script:Cur = $null; return $true }
        'status' { [void](Exe-Check); Write-Status; [IO.File]::WriteAllText($c.out, ([IO.File]::ReadAllText($StatusPath, $Utf8)) + "`r`n", $Utf8); Finish-Job $c 0 'ok' $null; $script:Cur = $null; return $true }
        'restart' { [IO.File]::WriteAllText($c.out, "watcher restarting (re-reads watcher.ps1)`r`n", $Utf8); Finish-Job $c 0 'ok' $null; $script:Cur = $null; $script:RestartAfter = $(if ($c.args -contains 'full') { 4 } else { 3 }); return $true }
        'update' {
            $kit = $hdr['kit']
            if (-not $kit -or -not (Is-ValidId $kit)) { Refuse-Job $c "usage: update kit=<kit id> (a harness kit folder under <state>\kits\)"; $script:Cur = $null; return $true }
            $kitDir = Join-Path (Join-Path (Split-Path $Root) 'kits') $kit
            if (-not (Test-Path -LiteralPath (Join-Path $kitDir 'manifest.json'))) { Refuse-Job $c "no kit at $kitDir (send it first: python3 proxy/tools/pc_deploy.py send --kit build/kits/<id> --state <state>; a kit id is never reused)"; $script:Cur = $null; return $true }
            $upd = RootPath (Join-Path 'update' "run_$(UtcStamp (Get-Date))")
            New-Item -ItemType Directory -Path $upd -Force | Out-Null
            Copy-Item -LiteralPath (Join-Path $SrcDir 'update.ps1') -Destination (Join-Path $upd 'update.ps1')     # run a COPY: the update replaces src\update.ps1 itself
            $cl = "powershell.exe -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$(Join-Path $upd 'update.ps1')`" -Root `"$Root`" -Kit `"$kitDir`""
            if ($hdr['noop_s']) { $cl += " -NoopS $([int]$hdr['noop_s'])" }
            if ($hdr['healthy_s']) { $cl += " -HealthyS $([int]$hdr['healthy_s'])" }
            if ($hdr['stable_s']) { $cl += " -StableS $([int]$hdr['stable_s'])" }
            $r = Start-Detached $cl $upd
            $x = Exe-Check
            [IO.File]::WriteAllText($c.out, "update started detached (rc=$($r.ReturnValue) pid=$($r.ProcessId)); log: $upd\update.log and watcher.log ([update] lines). Watch watcher.status version.`r`nexe: $(if ($x.ok -eq $true) { 'ok' } elseif ($x.ok -eq $false) { 'MISMATCH' } else { 'unchecked' }) - $($x.detail)`r`n", $Utf8)
            Finish-Job $c 0 'ok' $null; $script:Cur = $null; return $true
        }
    }
    # everything below launches/kills the game or changes its configs: the owner must hold game.lock
    $r = Check-Owner $c.owner
    if ($r) { Refuse-Job $c $r; $script:Cur = $null; return $true }
    $c.holds_game = $true
    $err = $null
    try {
        switch ($c.type) {
            'launch' { $err = Launch-Job $hdr $c $o }
            'kill' { $ok = Kill-Game "kill job $id owner=$($c.owner)" $o; if (-not $ok) { $err = 'ZOMBIE: the process survived taskkill /F /T - PC needs reboot' }; $script:LaunchAt = $null }
            'profile' {
                $name = $c.args | Select-Object -First 1
                if (-not $name) { $err = 'usage: profile <name>|restore owner=<you>' }
                elseif ($name -eq 'restore') { $err = Profile-Restore "profile restore job $id owner=$($c.owner)" $o }
                else { $err = Profile-Apply $name $c.owner $o }
            }
            default { $err = "unknown job type '$($c.type)' (cmd, ps1, launch, kill, profile, status, noop, restart, update)" }
        }
    } catch { $err = "watcher error: $($_.Exception.Message) (line $($_.InvocationInfo.ScriptLineNumber))" }
    [IO.File]::WriteAllText($c.out, (($o -join "`r`n") + "`r`n"), $Utf8)
    if ($err) {
        $st = if ($err -match '^ZOMBIE|^PC NEEDS REBOOT|^HEADLESS FAILED|did not verify|watcher error|did not appear') { 'failed' } else { 'refused' }
        if ($st -eq 'refused') { [IO.File]::AppendAllText($c.out, "REFUSED by watcher: $err`r`n", $Utf8) }
        Finish-Job $c $(if ($st -eq 'refused') { -2 } else { 1 }) $st $err
    } else { Finish-Job $c 0 'ok' $null }
    $script:Cur = $null
    return $true
}
function Poll-Cur {
    $c = $Cur
    if (-not $c) { return }
    if (-not $c.proc) {
        Log "job $($c.id): left in the slot without a process (starting it threw) - closing it as failed"
        Close-Job $c -1 'failed' 'watcher error while starting the job (see watcher.log)'
        return
    }
    if ($c.proc.HasExited) {
        $exit = -1
        try { $c.proc.WaitForExit(); $exit = $c.proc.ExitCode } catch { Log "job $($c.id): could not read the exit code: $($_.Exception.Message)" }
        Close-Job $c $exit $(if ($exit -eq 0) { 'ok' } else { 'failed' }) $null
        return
    }
    if (((Get-Date) - $c.started).TotalSeconds -gt $c.timeout) {
        Log "job $($c.id): timeout after $($c.timeout) s - killing its process tree (the game is spared)"
        $keep = @(@($A.game_image) + @($A.other_images) + @('steam.exe'))
        try { Kill-Tree-Except $c.proc.Id $keep } catch { Log "job $($c.id): killing the process tree failed: $($_.Exception.Message)" }
        Start-Sleep -Milliseconds 500
        Close-Job $c -1 'timeout' "no exit after $($c.timeout) s (#job timeout=N to change)"
    }
}
function Prune {
    $cut = (Get-Date).AddHours(-(IntSet 'prune_hours'))
    $n = 0
    Get-ChildItem -LiteralPath $JobsDir -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt $cut -and -not $_.Name.EndsWith('.request') -and $_.Name -ne '_ids.txt' } | ForEach-Object { Remove-Quiet $_.FullName; $n++ }
    if ($n) { Log "prune: removed $n job files older than $($S.prune_hours) h" }
    if (Test-Path -LiteralPath $IdsPath) {   # the id index outlives the result files (30 days)
        try {
            $keep = @([IO.File]::ReadAllLines($IdsPath) | Where-Object { $_ -and ([DateTime]::Parse($_.Split(' ')[0], $Inv, [Globalization.DateTimeStyles]::AdjustToUniversal) -gt (UtcNow).AddDays(-30)) })
            [IO.File]::WriteAllText($IdsPath, (($keep -join "`r`n") + $(if ($keep.Count) { "`r`n" } else { '' })), $Utf8)
        } catch { Log "prune: could not trim _ids.txt: $($_.Exception.Message)" }
    }
    $script:LastPrune = Get-Date
}
function Ensure-Dirs {
    foreach ($d in @($JobsDir, $ProfilesDir, $SavedDir, (RootPath 'runs'))) { if (-not (Test-Path -LiteralPath $d)) { New-Item -ItemType Directory -Path $d -Force | Out-Null } }
}

if ($NoRun) { return }

# ------------------------------------------------------------------------------------------------ single instance ---
$RootHash = [BitConverter]::ToString((New-Object Security.Cryptography.SHA1Managed).ComputeHash($Utf8.GetBytes($Root.ToLower()))).Replace('-', '').Substring(0, 16)
$Mutex = New-Object Threading.Mutex($false, "Local\warscape_watcher_$RootHash")
$owned = $false
try { $owned = $Mutex.WaitOne(0) } catch [Threading.AbandonedMutexException] { $owned = $true }
if (-not $owned) {
    $other = ''
    try { $other = [IO.File]::ReadAllText((RootPath 'watcher.pid')).Trim() } catch { }
    if (-not (Test-Path -LiteralPath $Root)) { New-Item -ItemType Directory -Path $Root -Force | Out-Null }
    Log "watcher: another watcher already serves $Root (pid $other) - this copy exits"
    exit 10
}
if (-not (Test-Path -LiteralPath $Root)) { New-Item -ItemType Directory -Path $Root -Force | Out-Null }
if (-not $A) { Log "watcher: adapter not found: $Adapter"; exit 2 }
Ensure-Dirs
[IO.File]::WriteAllText((RootPath 'watcher.pid'), "$PID", $Utf8)
if (Test-Path -LiteralPath $ZombiePath) { try { $Zombie = [IO.File]::ReadAllText($ZombiePath, $Utf8) | ConvertFrom-Json } catch { } }

# ------------------------------------------------------------------------------------------------ main loop ---------
# A previous watcher stopped or crashed mid-job: close those jobs ('lost') so nobody waits forever; re-queue claimed-but-not-started ones.
Get-ChildItem -LiteralPath $JobsDir -File -ErrorAction SilentlyContinue | Where-Object { $_.Name -match '^(.+)\.(run\.(cmd|ps1)|taken)$' } | ForEach-Object {
    $jid = $Matches[1]; $dn = Join-Path $JobsDir "$jid.done"
    if ($_.Name.EndsWith('.taken')) { Move-Item -LiteralPath $_.FullName -Destination (Join-Path $JobsDir "$jid.request") -Force; Log "job $jid re-queued (claimed but not started by the previous watcher)"; return }
    if (-not (Test-Path -LiteralPath $dn)) {
        $d = [ordered]@{ id = $jid; type = 'unknown'; owner = $null; exit = -1; status = 'lost'; reason = 'the watcher stopped while this job ran; output is partial'; start_utc = $null; end_utc = (UtcStr (Get-Date)); watcher = $Version }
        Write-Atomic $dn ($d | ConvertTo-Json); Log "job $jid closed as lost (watcher restarted mid-job)"
        $part = Join-Path $JobsDir "$jid.part"; $outp = Join-Path $JobsDir "$jid.out"
        if ((Test-Path -LiteralPath $part) -and -not (Test-Path -LiteralPath $outp)) { try { Copy-Item -LiteralPath $part -Destination $outp -Force } catch { } }
    }
    Remove-Quiet $_.FullName
}
Log "watcher $Version started (pid $PID, root $Root, game $($A.game), powershell $($PSVersionTable.PSVersion), up $(Up-Ms) ms after its process started)"
# the first heartbeat goes out before the first housekeeping pass: that pass (watchdog, auto-restore, display restore) can take
# seconds on a cold machine, and a waiter that reads a missing heartbeat as "not started" then times out (J42: CI's 40 s
# 'a fresh watcher heartbeat' and update rollback 1's revert, runs 40909011779, 40956451648)
Write-Alive
$FirstPass = $true
if ($Zombie) { Log "watcher: zombie flag carried over: pid $($Zombie.pid) since $($Zombie.since)" }
$exitCode = 0
while ($true) {
    try {
        $passAt = Get-Date
        Pump
        if ($FirstPass) { Log "watcher: first housekeeping pass took $([int]((Get-Date) - $passAt).TotalMilliseconds) ms"; $FirstPass = $false }
        Poll-Cur
        if (-not $Cur) { [void](Start-NextJob) }
        if (-not $Cur) {
            if (Test-Path -LiteralPath (RootPath 'restart.request')) { Remove-Quiet (RootPath 'restart.request'); Log 'restart.request'; $RestartAfter = 3 }
            if (Test-Path -LiteralPath (RootPath 'watcher.stop')) { Remove-Quiet (RootPath 'watcher.stop'); Log 'watcher.stop: stopping'; $exitCode = 11; break }
            if ($RestartAfter) { $exitCode = $RestartAfter; Log "watcher restarting (exit $exitCode)"; break }
        }
        if (((Get-Date) - $LastPrune).TotalMinutes -ge 10) { Prune }
    } catch {
        Log "loop error: $($_.Exception.Message) (line $($_.InvocationInfo.ScriptLineNumber))"
        if ($Cur -and -not $Cur.proc) { Close-Job $Cur -1 'failed' "watcher error while starting the job: $($_.Exception.Message)" }   # the slot is freed even when starting threw
        Start-Sleep -Seconds 2
    }
    Start-Sleep -Milliseconds (IntSet 'loop_ms')
}
try { $Mutex.ReleaseMutex() } catch { }
exit $exitCode
