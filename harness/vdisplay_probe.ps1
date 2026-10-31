# purpose: the virtual display tool: probe the Virtual Display Driver's modes (CDS_TEST), check it is the one display at the wanted size (-Check), set its mode (-Set), move its origin (-Origin) and put both back (-Restore); every change touches ONLY the display selected by name, never a real monitor
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File vdisplay_probe.ps1 [-Test 1920x1080,2560x1440] [-Hz n] [-Name "Virtual Display Driver"] | -Check -Size WxH | -Set WxH [-Hz n] -SaveTo <json> | -Origin X,Y -SaveTo <json> | -Restore <json>   (as a watcher ps1 job or called by the watcher's launch; exit 0 ok, 2 bad arguments, 3 no unique virtual display (VIRTUAL MISSING), 4 wrong size (VIRTUAL WRONG SIZE), 5 apply failed or did not verify, 6 mode not offered, 7 refused (primary, name mismatch, overlap, -SaveTo exists))
# when: before every headless launch (the watcher runs -Check, then -Set when the size differs, and -Restore after the game exits); to probe which modes the driver offers; to move the virtual display's origin in a topology test (the only display change an agent may make)
# not-a-verb: runs on the PC under Windows PowerShell 5.1, outside the repo checkout
# Safety: selection is a pure function (Select-VirtualDisplay) that returns a display only when exactly one ATTACHED, NON-PRIMARY display matches the name by adapter or monitor string; no fallback by size, index or DISPLAYn. The only apply calls are in Cds-Test / Cds-Apply, which take that selection (not a string) and refuse a primary or null. Dynamic changes only (flags 0): nothing persists in the registry, no SetDisplayConfig. Every display is printed before and after, and a change to any other display is a loud warning.
# Ported from empire-remastered rml_mod/tools/remote/vdisplay_mode.ps1 (-Modes / -Res / -Origin / restore paths), narrowed: no -Persist, no refresh-rate switching for perf runs, no selector but the name.
param([string[]]$Test = @('1920x1080', '2560x1440'), [int]$Hz = 0, [string]$Name = 'Virtual Display Driver',
      [switch]$Check, [string]$Size = '', [string]$Set = '', [string[]]$Origin = @(), [string]$SaveTo = '', [string]$Restore = '', [switch]$LibOnly)
$ErrorActionPreference = 'Stop'

# ---- pure logic (no Windows calls; Test-Unit.ps1 dot-sources this file with -LibOnly and feeds it fake display lists) -----------------
# A display: Device, Adapter, Monitor, Primary, W, H, Hz, X, Y (attached displays only).
# Returns @{ display; reason; matches }. display is non-null ONLY for exactly one attached, non-primary display whose adapter or monitor string contains $name.
function Select-VirtualDisplay($displays, [string]$name) {
    $r = @{ display = $null; reason = ''; matches = @() }
    if (-not $name) { $r.reason = 'no display name given'; return $r }
    $m = @($displays | Where-Object { $_.Adapter -like "*$name*" -or $_.Monitor -like "*$name*" })
    $r.matches = $m
    if ($m.Count -eq 0) { $r.reason = "no attached display matches '$name' (driver not installed or disabled)"; return $r }
    if ($m.Count -gt 1) { $r.reason = "$($m.Count) displays match '$name' ($((@($m | ForEach-Object { $_.Device })) -join ', ')): not unique, refusing to pick one"; return $r }
    if ($m[0].Primary) { $r.reason = "the only display matching '$name' ($($m[0].Device)) is the PRIMARY display: refusing to touch it"; return $r }
    $r.display = $m[0]
    return $r
}
function Parse-Size([string]$s) {
    if ($s -match '^\s*(\d{3,5})x(\d{3,5})\s*$') { return @{ w = [int]$Matches[1]; h = [int]$Matches[2] } }
    return $null
}
function Test-RectOverlap($a, $b) { return ($a.L -lt $b.R -and $b.L -lt $a.R -and $a.T -lt $b.B -and $b.T -lt $a.B) }
function Get-DisplayRect($d, $x, $y) { return @{ L = [int]$x; T = [int]$y; R = [int]$x + [int]$d.W; B = [int]$y + [int]$d.H } }
# The move plan for the selected display: refuses a rect that overlaps any OTHER display (touching edges are fine).
function Get-OriginPlan($displays, $sel, [int]$x, [int]$y) {
    if (-not $sel.display) { return @{ ok = $false; reason = $sel.reason } }
    $t = $sel.display
    $nr = Get-DisplayRect $t $x $y
    foreach ($o in $displays) {
        if ($o.Device -eq $t.Device) { continue }
        if (Test-RectOverlap $nr (Get-DisplayRect $o $o.X $o.Y)) { return @{ ok = $false; reason = "the new rect $($nr.L),$($nr.T)-$($nr.R),$($nr.B) overlaps $($o.Device) at $($o.X),$($o.Y) ($($o.W)x$($o.H))" } }
    }
    return @{ ok = $true; reason = ''; x = $x; y = $y }
}
# Candidate refresh rates for -Set: the requested one, else the current then 60.
function Get-HzCandidates([int]$wanted, [int]$current) {
    if ($wanted -gt 0) { return @($wanted) }
    return @(@($current, 60) | Where-Object { $_ -gt 0 } | Select-Object -Unique)
}
# Every display other than $exceptDevice whose mode, origin or primary flag differs between two lists (by device name).
function Get-OtherChanges($before, $after, [string]$exceptDevice) {
    $c = @()
    foreach ($b in $before) {
        if ($b.Device -eq $exceptDevice) { continue }
        $a = @($after | Where-Object { $_.Device -eq $b.Device })
        if (-not $a.Count) { $c += "$($b.Device) is gone"; continue }
        $a = $a[0]
        if ($a.W -ne $b.W -or $a.H -ne $b.H -or $a.X -ne $b.X -or $a.Y -ne $b.Y -or $a.Primary -ne $b.Primary -or $a.Hz -ne $b.Hz) {
            $c += "$($b.Device) changed: $($b.W)x$($b.H)@$($b.Hz) at $($b.X),$($b.Y) primary=$($b.Primary) -> $($a.W)x$($a.H)@$($a.Hz) at $($a.X),$($a.Y) primary=$($a.Primary)"
        }
    }
    foreach ($a in $after) { if ($a.Device -ne $exceptDevice -and -not @($before | Where-Object { $_.Device -eq $a.Device }).Count) { $c += "$($a.Device) appeared" } }
    return $c
}
function Format-Display($d) {
    return ("{0,-14} {1}x{2}@{3}Hz at {4},{5}{6}  adapter='{7}' monitor='{8}'" -f $d.Device, $d.W, $d.H, $d.Hz, $d.X, $d.Y, $(if ($d.Primary) { ' PRIMARY' } else { '' }), $d.Adapter, $d.Monitor)
}
# Windows recentres the real cursor on a dynamic mode change: when the cursor now sits exactly at the centre of a display (that
# signature, so a move Liam made meanwhile is left alone) and was elsewhere before the change, it goes back where it was.
function Get-CursorDecision($before, $now, $displays) {
    if ($before[0] -eq $now[0] -and $before[1] -eq $now[1]) { return $false }
    foreach ($d in @($displays)) {
        $cx = [int][Math]::Floor($d.X + $d.W / 2); $cy = [int][Math]::Floor($d.Y + $d.H / 2)
        if ([Math]::Abs($now[0] - $cx) -le 1 -and [Math]::Abs($now[1] - $cy) -le 1) { return $true }
    }
    return $false
}
if ($LibOnly) { return }

Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class VProbe {
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DISPLAY_DEVICE {
        public int cb;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString;
        public int StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey;
    }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)]
    public struct DEVMODE {
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmDeviceName;
        public short dmSpecVersion, dmDriverVersion, dmSize, dmDriverExtra;
        public int dmFields;
        public int dmPositionX, dmPositionY;
        public int dmDisplayOrientation, dmDisplayFixedOutput;
        public short dmColor, dmDuplex, dmYResolution, dmTTOption, dmCollate;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string dmFormName;
        public short dmLogPixels;
        public int dmBitsPerPel, dmPelsWidth, dmPelsHeight, dmDisplayFlags, dmDisplayFrequency;
        public int dmICMMethod, dmICMIntent, dmMediaType, dmDitherType, dmReserved1, dmReserved2, dmPanningWidth, dmPanningHeight;
    }
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool EnumDisplayDevices(string lpDevice, int iDevNum, ref DISPLAY_DEVICE lpDisplayDevice, int dwFlags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool EnumDisplaySettings(string deviceName, int modeNum, ref DEVMODE devMode);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern bool EnumDisplaySettingsEx(string deviceName, int modeNum, ref DEVMODE devMode, int dwFlags);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    public static extern int ChangeDisplaySettingsEx(string lpszDeviceName, ref DEVMODE lpDevMode, IntPtr hwnd, int dwflags, IntPtr lParam);
    // A dynamic mode change makes Windows move the REAL cursor to the centre of the primary (J13 PC run, 2026-10-29): read it before
    // and put it back after, physical pixels (per-monitor aware V2).
    [StructLayout(LayoutKind.Sequential)] public struct POINT { public int X, Y; }
    [DllImport("user32.dll")] static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] static extern bool SetCursorPos(int x, int y);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr c);
    public static int[] CursorNow() { var o = SetThreadDpiAwarenessContext(new IntPtr(-4)); POINT p; GetCursorPos(out p); if (o != IntPtr.Zero) SetThreadDpiAwarenessContext(o); return new int[] { p.X, p.Y }; }
    public static bool CursorTo(int x, int y) { var o = SetThreadDpiAwarenessContext(new IntPtr(-4)); bool r = SetCursorPos(x, y); if (o != IntPtr.Zero) SetThreadDpiAwarenessContext(o); return r; }
    public const int EDS_RAWMODE = 0x2, ATTACHED = 0x1, PRIMARY = 0x4, ENUM_CURRENT_SETTINGS = -1;
    public const int DM_PELSWIDTH = 0x80000, DM_PELSHEIGHT = 0x100000, DM_BITSPERPEL = 0x40000, DM_DISPLAYFREQUENCY = 0x400000, DM_DISPLAYFIXEDOUTPUT = 0x20000000;
    public const int CDS_TEST = 0x2, DM_POSITION = 0x20;
}
'@

function New-DevMode { $m = New-Object VProbe+DEVMODE; $m.dmSize = [int16][Runtime.InteropServices.Marshal]::SizeOf([type][VProbe+DEVMODE]); $m }
function Dcs([int]$rc) { switch ($rc) { 0 { 'DISP_CHANGE_SUCCESSFUL' } 1 { 'DISP_CHANGE_RESTART' } -1 { 'DISP_CHANGE_FAILED' } -2 { 'DISP_CHANGE_BADMODE' } -3 { 'DISP_CHANGE_NOTUPDATED' } -4 { 'DISP_CHANGE_BADFLAGS' } -5 { 'DISP_CHANGE_BADPARAM' } default { "code $rc" } } }
function Get-Displays {
    $list = @()
    for ($i = 0; $i -lt 64; $i++) {
        $dd = New-Object VProbe+DISPLAY_DEVICE; $dd.cb = [Runtime.InteropServices.Marshal]::SizeOf([type][VProbe+DISPLAY_DEVICE])
        if (-not [VProbe]::EnumDisplayDevices([NullString]::Value, $i, [ref]$dd, 0)) { break }
        if (-not ($dd.StateFlags -band [VProbe]::ATTACHED)) { continue }
        $md = New-Object VProbe+DISPLAY_DEVICE; $md.cb = $dd.cb
        $mon = ''; if ([VProbe]::EnumDisplayDevices($dd.DeviceName, 0, [ref]$md, 0)) { $mon = $md.DeviceString }
        $cur = New-DevMode; [void][VProbe]::EnumDisplaySettings($dd.DeviceName, [VProbe]::ENUM_CURRENT_SETTINGS, [ref]$cur)
        $list += [pscustomobject]@{ Device = $dd.DeviceName; Adapter = $dd.DeviceString; Monitor = $mon; Primary = [bool]($dd.StateFlags -band [VProbe]::PRIMARY); W = $cur.dmPelsWidth; H = $cur.dmPelsHeight; Hz = $cur.dmDisplayFrequency; X = $cur.dmPositionX; Y = $cur.dmPositionY }
    }
    return $list
}
function Show-Displays([string]$title, $list) {
    Write-Output "$title ($(@($list).Count) attached):"
    foreach ($d in $list) { Write-Output ('  ' + (Format-Display $d)) }
}
# The ONLY two functions that call ChangeDisplaySettingsEx. They take the selection, not a device string, and re-check it.
function Assert-Selected($sel) {
    if (-not $sel -or -not $sel.display) { throw "refusing: no selected virtual display ($($sel.reason))" }
    if ($sel.display.Primary) { throw "refusing: $($sel.display.Device) is the primary display" }
}
function Cds-Test($sel, $dm) { Assert-Selected $sel; return [VProbe]::ChangeDisplaySettingsEx($sel.display.Device, [ref]$dm, [IntPtr]::Zero, [VProbe]::CDS_TEST, [IntPtr]::Zero) }
function Cds-Apply($sel, $dm) { Assert-Selected $sel; return [VProbe]::ChangeDisplaySettingsEx($sel.display.Device, [ref]$dm, [IntPtr]::Zero, 0, [IntPtr]::Zero) }   # flags 0 = dynamic, never persisted
function New-ModeFor($t, [int]$w, [int]$h, [int]$hz, [int]$x, [int]$y) {
    $dm = New-DevMode
    [void][VProbe]::EnumDisplaySettings($t.Device, [VProbe]::ENUM_CURRENT_SETTINGS, [ref]$dm)
    $dm.dmPelsWidth = $w; $dm.dmPelsHeight = $h; $dm.dmDisplayFrequency = $hz; $dm.dmBitsPerPel = 32; $dm.dmPositionX = $x; $dm.dmPositionY = $y
    $dm.dmFields = [VProbe]::DM_PELSWIDTH -bor [VProbe]::DM_PELSHEIGHT -bor [VProbe]::DM_DISPLAYFREQUENCY -bor [VProbe]::DM_BITSPERPEL -bor [VProbe]::DM_POSITION
    return $dm
}
function Write-MissingModeHelp($missing, [int]$hz) {
    if ($hz -le 0) { $hz = 60 }
    Write-Output ''
    Write-Output "NOT OFFERED by the driver: $($missing -join ', '). The change for Liam (administrator; agents never do this):"
    Write-Output '  1. Open Notepad as administrator, open C:\VirtualDisplayDriver\vdd_settings.xml.'
    Write-Output '  2. Inside <resolutions>...</resolutions> add one block per missing size, keeping the existing 3840x2160 blocks:'
    foreach ($m in ($missing | Select-Object -Unique)) {
        $p = $m -split 'x'
        Write-Output "       <resolution><width>$($p[0])</width><height>$($p[1])</height><refresh_rate>$hz</refresh_rate></resolution>"
    }
    Write-Output '  3. The file must still start with <?xml as its very first characters (no blank line before it). Save.'
    Write-Output '  4. VDD Control -> Reload driver (or Device Manager: disable, enable the Virtual Display Driver). Reboot if nothing changes.'
    Write-Output '  5. Run this tool again.'
}
function Fail-NoSel($sel) { Write-Output "VIRTUAL MISSING: $($sel.reason). Nothing was changed."; exit 3 }
function Report-After($before, $t, [string]$what) {
    $after = @(Get-Displays)
    Show-Displays "displays after $what" $after
    $oc = @(Get-OtherChanges $before $after $t.Device)
    if ($oc.Count) { foreach ($c in $oc) { Write-Output "WARNING: ANOTHER DISPLAY CHANGED: $c" } } else { Write-Output "other displays unchanged ($(@($after).Count - 1) checked)" }
    return $after
}
function Put-CursorBack($before, $displays) {
    $now = [VProbe]::CursorNow()
    if (Get-CursorDecision $before $now $displays) {
        [void][VProbe]::CursorTo($before[0], $before[1])
        Write-Output ("cursor: Windows moved it to {0},{1} (a display centre) with the mode change; put back at {2},{3}" -f $now[0], $now[1], $before[0], $before[1])
    }
}
# Applies size and/or origin to the selected display: CDS_TEST first, then dynamic apply, then verify by re-reading the displays.
function Apply-ToVirtual($all, $sel, [int]$w, [int]$h, [int]$hzWanted, [int]$x, [int]$y, [string]$what) {
    $t = $sel.display
    $dmOk = $null; $usedHz = 0; $rc = 0
    foreach ($hz in (Get-HzCandidates $hzWanted $t.Hz)) {
        $dm = New-ModeFor $t $w $h $hz $x $y
        $rc = Cds-Test $sel $dm
        Write-Output ("CDS_TEST({0}, {1}x{2}@{3} at {4},{5}) -> {6} ({7})" -f $t.Device, $w, $h, $hz, $x, $y, $rc, (Dcs $rc))
        if ($rc -eq 0) { $dmOk = $dm; $usedHz = $hz; break }
    }
    if (-not $dmOk) {
        Write-Output "MODE NOT OFFERED: ${w}x${h} is refused by the driver for $($t.Device); nothing was changed."
        Write-MissingModeHelp @("${w}x${h}") $hzWanted
        exit 6
    }
    $cur0 = [VProbe]::CursorNow()
    $rc = Cds-Apply $sel $dmOk
    Write-Output ("ChangeDisplaySettingsEx({0}, {1}x{2}@{3} at {4},{5}, dynamic) -> {6} ({7})" -f $t.Device, $w, $h, $usedHz, $x, $y, $rc, (Dcs $rc))
    Start-Sleep -Milliseconds 1500
    $after = Report-After $all $t $what
    Put-CursorBack $cur0 $after
    $now = @($after | Where-Object { $_.Device -eq $t.Device })
    if ($rc -ne 0 -or -not $now.Count -or $now[0].W -ne $w -or $now[0].H -ne $h -or $now[0].X -ne $x -or $now[0].Y -ne $y) {
        Write-Output "APPLY FAILED: $($t.Device) is not ${w}x${h} at $x,$y after the change"
        exit 5
    }
    return $now[0]
}
function Save-Prev($t, [string]$path) {
    if (-not $path) { Write-Output 'bad arguments: this mode needs -SaveTo <json> (the previous mode is saved there so it can be restored)'; exit 2 }
    if (Test-Path -LiteralPath $path) { Write-Output "REFUSED: -SaveTo file exists ($path): restore (or move) it first, or the real previous mode would be overwritten"; exit 7 }
    $o = [ordered]@{ name = $Name; device = $t.Device; adapter = $t.Adapter; monitor = $t.Monitor; w = $t.W; h = $t.H; hz = $t.Hz; x = $t.X; y = $t.Y; saved_utc = (Get-Date).ToUniversalTime().ToString('yyyy-MM-dd\THH:mm:ss\Z', [Globalization.CultureInfo]::InvariantCulture) }
    [IO.File]::WriteAllText($path, ($o | ConvertTo-Json), (New-Object Text.UTF8Encoding $false))
    Write-Output "previous mode saved to ${path}: $($t.W)x$($t.H)@$($t.Hz) at $($t.X),$($t.Y)"
}

# ---- modes ------------------------------------------------------------------------------------------------------------------------------
$all = @(Get-Displays)
$sel = Select-VirtualDisplay $all $Name
Show-Displays 'displays' $all

if ($Check) {
    $sz = Parse-Size $Size
    if (-not $sz) { Write-Output "bad arguments: -Check needs -Size WxH (got '$Size')"; exit 2 }
    if (-not $sel.display) { Fail-NoSel $sel }
    $t = $sel.display
    $rect = "{0},{1},{2},{3}" -f $t.X, $t.Y, ($t.X + $t.W), ($t.Y + $t.H)
    if ($t.W -ne $sz.w -or $t.H -ne $sz.h) {
        Write-Output ("VIRTUAL WRONG SIZE: {0} is {1}x{2}@{3}Hz but {4}x{5} is wanted (rect={6})" -f $t.Device, $t.W, $t.H, $t.Hz, $sz.w, $sz.h, $rect)
        exit 4
    }
    Write-Output ("VIRTUAL OK: {0} {1}x{2}@{3}Hz rect={4} adapter='{5}' monitor='{6}'" -f $t.Device, $t.W, $t.H, $t.Hz, $rect, $t.Adapter, $t.Monitor)
    exit 0
}
if ($Set) {
    $sz = Parse-Size $Set
    if (-not $sz) { Write-Output "bad arguments: -Set needs WxH (got '$Set')"; exit 2 }
    if (-not $sel.display) { Fail-NoSel $sel }
    $t = $sel.display
    if ($t.W -eq $sz.w -and $t.H -eq $sz.h) { Write-Output "VIRTUAL OK: $($t.Device) is already $($sz.w)x$($sz.h); nothing to do"; exit 0 }
    Save-Prev $t $SaveTo
    [void](Apply-ToVirtual $all $sel $sz.w $sz.h $Hz $t.X $t.Y 'the mode change')
    Write-Output "VIRTUAL SET: $($t.Device) now $($sz.w)x$($sz.h) (was $($t.W)x$($t.H)@$($t.Hz)); restore with -Restore $SaveTo"
    exit 0
}
$Origin = (@($Origin) -join ',')   # "& tool -Origin 3840,0" arrives as an array (J13 PC run d)
if ($Origin) {
    $om = [regex]::Match($Origin, '^\s*(-?\d+)\s*,\s*(-?\d+)\s*$')   # not -notmatch: it leaves $Matches empty
    if (-not $om.Success) { Write-Output "bad arguments: -Origin needs X,Y (got '$Origin')"; exit 2 }
    $ox = [int]$om.Groups[1].Value; $oy = [int]$om.Groups[2].Value
    if (-not $sel.display) { Fail-NoSel $sel }
    $t = $sel.display
    $plan = Get-OriginPlan $all $sel $ox $oy
    if (-not $plan.ok) { Write-Output "REFUSED: $($plan.reason). Nothing was changed."; exit 7 }
    if ($t.X -eq $ox -and $t.Y -eq $oy) { Write-Output "VIRTUAL OK: $($t.Device) is already at $ox,$oy; nothing to do"; exit 0 }
    Save-Prev $t $SaveTo
    [void](Apply-ToVirtual $all $sel $t.W $t.H $t.Hz $ox $oy 'the origin move')
    Write-Output "VIRTUAL MOVED: $($t.Device) now at $ox,$oy (was $($t.X),$($t.Y)); restore with -Restore $SaveTo"
    exit 0
}
if ($Restore) {
    if (-not (Test-Path -LiteralPath $Restore)) { Write-Output "bad arguments: $Restore does not exist"; exit 2 }
    $p = [IO.File]::ReadAllText($Restore) | ConvertFrom-Json
    if ($p.name -and $p.name -ne $Name) { Write-Output "REFUSED: $Restore was saved for '$($p.name)', not '$Name'"; exit 7 }
    if (-not $sel.display) { Fail-NoSel $sel }
    $t = $sel.display
    if ($t.W -eq $p.w -and $t.H -eq $p.h -and $t.X -eq $p.x -and $t.Y -eq $p.y) { Write-Output "VIRTUAL OK: $($t.Device) is already back at $($p.w)x$($p.h) at $($p.x),$($p.y)"; exit 0 }
    $plan = Get-OriginPlan $all $sel ([int]$p.x) ([int]$p.y)
    if (-not $plan.ok) { Write-Output "REFUSED: $($plan.reason). Nothing was changed."; exit 7 }
    [void](Apply-ToVirtual $all $sel ([int]$p.w) ([int]$p.h) ([int]$p.hz) ([int]$p.x) ([int]$p.y) 'the restore')
    Write-Output "VIRTUAL RESTORED: $($t.Device) back at $($p.w)x$($p.h)@$($p.hz) at $($p.x),$($p.y)"
    exit 0
}

# ---- probe (today's behaviour): CDS_TEST only ------------------------------------------------------------------------------------------
if (-not $sel.display) {
    Write-Output "NO UNIQUE VIRTUAL DISPLAY: $($sel.reason). Nothing was changed."
    exit 3
}
$target = $sel.display
if ($Hz -le 0) { $Hz = 60 }
Write-Output "target: $($target.Device) (non-primary, matched by name '$Name'); current mode $($target.W)x$($target.H)@$($target.Hz)Hz"
foreach ($flag in 0, [VProbe]::EDS_RAWMODE) {
    $seen = @{}
    for ($n = 0; $n -lt 8192; $n++) {
        $m = New-DevMode
        if (-not [VProbe]::EnumDisplaySettingsEx($target.Device, $n, [ref]$m, $flag)) { break }
        $seen["{0}x{1}@{2}/{3}bpp" -f $m.dmPelsWidth, $m.dmPelsHeight, $m.dmDisplayFrequency, $m.dmBitsPerPel] = 1
    }
    Write-Output ("mode list ({0}, {1} modes): {2}" -f $(if ($flag) { 'EDS_RAWMODE' } else { 'normal' }), $seen.Count, (($seen.Keys | Sort-Object) -join ' '))
}
$missing = @(); $tested = 0
# -Test arrives as an array from a ps1 job (& script -Test a,b) and as one string from -File: split both on commas and spaces
foreach ($res in (($Test -join ',') -split '[,\s]+')) {
    $res = $res.Trim(); if (-not $res) { continue }
    $sz = Parse-Size $res
    if (-not $sz) { Write-Output "bad -Test entry '$res': want WxH"; exit 2 }
    $tested++
    $w = $sz.w; $h = $sz.h
    foreach ($fx in 0, 1, 2) {   # 0 = driver mode as is, 1 = GPU stretch, 2 = GPU centre
        $dm = New-DevMode
        [void][VProbe]::EnumDisplaySettings($target.Device, [VProbe]::ENUM_CURRENT_SETTINGS, [ref]$dm)
        $dm.dmPelsWidth = $w; $dm.dmPelsHeight = $h; $dm.dmDisplayFrequency = $Hz; $dm.dmBitsPerPel = 32
        $dm.dmFields = [VProbe]::DM_PELSWIDTH -bor [VProbe]::DM_PELSHEIGHT -bor [VProbe]::DM_DISPLAYFREQUENCY -bor [VProbe]::DM_BITSPERPEL
        if ($fx -ne 0) { $dm.dmDisplayFixedOutput = $fx; $dm.dmFields = $dm.dmFields -bor [VProbe]::DM_DISPLAYFIXEDOUTPUT }
        $rc = Cds-Test $sel $dm   # CDS_TEST: validate only, nothing is applied
        Write-Output ("CDS_TEST({0}, {1}x{2}@{3}, fixed_output {4}) -> {5} ({6})" -f $target.Device, $w, $h, $Hz, $fx, $rc, (Dcs $rc))
        if ($fx -eq 0 -and $rc -ne 0) { $missing += "${w}x${h}" }
    }
}
$post = New-DevMode; [void][VProbe]::EnumDisplaySettings($target.Device, [VProbe]::ENUM_CURRENT_SETTINGS, [ref]$post)
if ($post.dmPelsWidth -ne $target.W -or $post.dmPelsHeight -ne $target.H -or $post.dmDisplayFrequency -ne $target.Hz) { Write-Output "WARNING: the target's mode changed during the probe (should be impossible with CDS_TEST)" }
else { Write-Output "unchanged: $($target.Device) is still $($post.dmPelsWidth)x$($post.dmPelsHeight)@$($post.dmDisplayFrequency)Hz" }
if ($missing.Count) { Write-MissingModeHelp $missing $Hz; exit 6 }
if ($tested -eq 0) { Write-Output 'no mode was tested (-Test empty): not a pass'; exit 2 }
Write-Output "all $tested tested modes are offered by the driver"
exit 0
