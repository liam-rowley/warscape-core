# purpose: tiny shared test kit for the harness host tests (Test-Case, assertions, Wait-Until, temp folders, a test adapter); dot-sourced by Test-Unit.ps1 and Test-Integration.ps1
# usage: . "$PSScriptRoot\Test-Lib.ps1"   (not run on its own)
# when: only from the harness host tests; ASCII only, no Pester (Windows PowerShell 5.1 ships Pester 3 and the runner another)
# not-a-verb: a dot-sourced PowerShell library for the host tests
$script:Pass = 0
$script:Fail = 0
$script:Failures = @()
$script:TcOnly = ''     # -Only <regex>: run only the cases whose name matches (set by the suite script after dot-sourcing)
$script:TcRepeat = 1    # -Repeat <n>: run each selected case n times, stop that case at its first failure
$script:Selected = 0
$script:TcOnFail = $null  # optional scriptblock run after a failed case (Test-Integration prints the watcher log tail: J42)
# The selection and repeat logic, pure so Test-Unit.ps1 can test it: runs $body up to $repeat times when $name matches $only,
# stops at the first throw. Returns ran (case selected), passed (runs that passed), error (the first failure's message or $null).
# Case bodies run in this function's dynamic scope and see its locals: they carry a tc prefix so no body reads one by accident.
function Invoke-Selected([string]$name, [scriptblock]$body, [string]$only, [int]$repeat, [scriptblock]$onStart = $null) {
    $tcRes = @{ ran = $false; passed = 0; error = $null }
    if ($only -and $name -notmatch $only) { return $tcRes }
    $tcRes.ran = $true
    for ($tcRun = 1; $tcRun -le [Math]::Max(1, $repeat); $tcRun++) {
        if ($onStart) { & $onStart $tcRun }
        try { & $body | Out-Null; $tcRes.passed++ } catch { $tcRes.error = $_.Exception.Message; break }
    }
    return $tcRes
}
function Test-Case([string]$name, [scriptblock]$body) {
    $tcN = [Math]::Max(1, $script:TcRepeat)
    # START per run: a hang shows which test it was in (J2 CI round 8 was cancelled with no log)
    $tcStart = { param($k) Write-Host "START $((Get-Date).ToUniversalTime().ToString('HH:mm:ss'))Z $name$(if ($tcN -gt 1) { " (run $k/$tcN)" })" }
    $tcRes = Invoke-Selected $name $body $script:TcOnly $tcN $tcStart
    if (-not $tcRes.ran) { return }
    $script:Selected++
    $script:Pass += $tcRes.passed
    $tcTally = if ($tcN -gt 1) { " ($($tcRes.passed)/$tcN runs passed)" } else { '' }
    if ($tcRes.error) {
        Write-Host "FAIL  $name$tcTally : $($tcRes.error)"; $script:Fail++; $script:Failures += $name
        if ($script:TcOnFail) { try { & $script:TcOnFail } catch { Write-Host "  (diagnostics failed: $($_.Exception.Message))" } }
    }
    else { Write-Host "PASS  $name$tcTally" }
}
function Assert-True($cond, [string]$msg) { if (-not $cond) { throw "assertion failed: $msg" } }
function Assert-Eq($actual, $expected, [string]$msg) { if ("$actual" -ne "$expected") { throw "$msg : expected [$expected] but got [$actual]" } }
function Short([string]$t) { if ($t.Length -gt 300) { return $t.Substring(0, 300) + '...' } else { return $t } }
function Assert-Match([string]$text, [string]$rx, [string]$msg) { if ($text -notmatch $rx) { throw "$msg : [$(Short $text)] does not match /$rx/" } }
function Assert-NotMatch([string]$text, [string]$rx, [string]$msg) { if ($text -match $rx) { throw "$msg : matched [$($Matches[0])] /$rx/" } }
function Wait-Until([scriptblock]$cond, [int]$secs, [string]$what) {
    $deadline = (Get-Date).AddSeconds($secs)
    while ((Get-Date) -lt $deadline) { $r = & $cond; if ($r) { return $r }; Start-Sleep -Milliseconds 300 }
    throw "timed out after $secs s waiting for: $what"
}
function New-Tmp([string]$tag) {
    $base = $env:RUNNER_TEMP; if (-not $base) { $base = [IO.Path]::GetTempPath() }
    $d = Join-Path $base ("wt_{0}_{1}" -f $tag, ([Guid]::NewGuid().ToString('N').Substring(0, 8)))
    New-Item -ItemType Directory -Path $d -Force | Out-Null
    return $d
}
$Utf8NoBom = New-Object Text.UTF8Encoding $false
function Sha256File([string]$p) { return (Get-FileHash -LiteralPath $p -Algorithm SHA256).Hash.ToLower() }
# A test adapter: fake game and AppData folders under $dir, the real config-file table (the ids a game adapter uses).
function New-TestAdapter([string]$dir, [string]$gameImage = 'Game.exe', [string]$otherImage = 'Other.exe', [string]$launchArgs = '') {
    $game = Join-Path $dir 'game'; $app = Join-Path $dir 'appdata'
    foreach ($d in @($game, (Join-Path $app 'scripts'), (Join-Path $game 'logs'))) { New-Item -ItemType Directory -Path $d -Force | Out-Null }
    $adapter = [ordered]@{
        game = 'testgame'; title = 'Test Game'; state_dir = $dir; watcher_subdir = 'watcher'; task_name = 'testmod watcher citest'
        game_dir = $game; appdata_dir = $app; game_image = $gameImage; other_images = @($otherImage)
        launch = [ordered]@{ route = 'exe'; exe = $gameImage; args = $launchArgs; steam_uri = ''; steam_wait_s = 5 }
        heartbeat_files = @('logs\proxy.log', 'testmod\headless_status.json')
        headless = [ordered]@{
            display_name = 'Virtual Display Driver'; default_size = '3840x2160'; status_file = 'testmod\headless_status.json'
            marker_file = 'd3d9.dll'; marker = 'headless_status.json'; exit_code = 2160
            prefs = [ordered]@{ x_res = '{W}'; y_res = '{H}'; gfx_fullscreen = 'false' }
            mod_ini = [ordered]@{ 'headless.enabled' = '1'; 'headless.size' = '{W}x{H}' }
        }
        archive = [ordered]@{ dirs_log = @('logs'); dirs_dump = @('dumps'); files = @('testmod.ini', 'dxvk.conf') }
        foreign_locks = @((Join-Path $dir 'foreign\game.lock'))
        virtualstore_guard = @('testmod')
        config_files = @(
            [ordered]@{ id = 'prefs'; anchor = 'appdata'; path = 'scripts\preferences.script.txt'; style = 'prefs' },
            [ordered]@{ id = 'keys'; anchor = 'appdata'; path = 'custom_keys.keys.xml'; style = 'none' },
            [ordered]@{ id = 'battle_prefs'; anchor = 'appdata'; path = 'battle_preferences\.sp_default.battle_preferences'; style = 'none' },
            [ordered]@{ id = 'mod_ini'; anchor = 'game'; path = 'testmod.ini'; style = 'ini' },
            [ordered]@{ id = 'dxvk_conf'; anchor = 'game'; path = 'dxvk.conf'; style = 'conf' }
        )
    }
    $path = Join-Path $dir 'adapter.json'
    [IO.File]::WriteAllText($path, ($adapter | ConvertTo-Json -Depth 6), $Utf8NoBom)
    return $path
}
function Finish-Tests([string]$suite) {
    Write-Host ''
    Write-Host "$suite : $($script:Pass) passed, $($script:Fail) failed$(if ($script:TcOnly) { " ($($script:Selected) cases matched -Only '$($script:TcOnly)')" })"
    if ($script:Fail) { Write-Host ('FAILED: ' + ($script:Failures -join '; ')) }
    # a filter that matches nothing is a typo, not a pass
    if ($script:TcOnly -and -not $script:Selected) { Write-Host "FAILED: no $suite case matches -Only '$($script:TcOnly)'"; return 1 }
    return $script:Fail
}
