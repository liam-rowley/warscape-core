# purpose: whole-launch window probe: from the game process start to its exit it samples every ~10 ms, re-reads the monitor list every sample, and records for every top-level window of the game whether it was visible / DWM-cloaked / iconic and where, so a headless launch is MEASURED (how long any game window sat visible on a real monitor), not sampled
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File win_probe.ps1 -OutDir <dir> [-Image <game exe> | -ProcessId <pid>] [-VirtualName "Virtual Display Driver"] [-WaitStartS 120] [-MaxS 14400]   (started detached by the watcher's launch job; writes <OutDir>\ready.txt when polling, winprobe.txt (live log + summary) and winprobe.json at the end; a file named stop in OutDir ends the wait for a game that never started)
# when: every watcher launch, headless or visible (the watcher starts it before the game); by hand when a window is suspected on the wrong monitor
# not-a-verb: runs on the PC under Windows PowerShell 5.1, outside the repo checkout
# Read only, no admin: it never changes a window, a display or a file outside -OutDir. A real monitor = any monitor that is not the virtual display; the virtual display is matched BY NAME (adapter or monitor string from EnumDisplayDevices, the same rule as vdisplay_probe.ps1), never by index. Per-monitor-DPI-aware V2, so every rect is physical pixels.
# Ported (design, not size) from empire-remastered rml_mod/tools/remote/headless_verify/win_probe.ps1. A window of at most 1x1 pixels (the engine's helper window) is listed but not counted as a violation.
param([Parameter(Mandatory = $true)][string]$OutDir, [string]$Image = '', [int]$ProcessId = 0, [string]$VirtualName = 'Virtual Display Driver', [int]$WaitStartS = 120, [int]$MaxS = 14400)
if (-not $Image -and -not $ProcessId) { Write-Output 'win_probe: give -Image <game exe> or -ProcessId <pid> (the watcher passes the adapter''s game_image)'; exit 2 }
$ErrorActionPreference = 'Stop'
New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
Add-Type -TypeDefinition @'
using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
public static class NWinProbe {
    [StructLayout(LayoutKind.Sequential)] public struct RECT { public int L, T, R, B; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct MONITORINFOEX {
        public int cbSize; public RECT rcMonitor; public RECT rcWork; public int dwFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string szDevice; }
    [StructLayout(LayoutKind.Sequential, CharSet = CharSet.Unicode)] public struct DISPLAY_DEVICE {
        public int cb; [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 32)] public string DeviceName;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceString; public int StateFlags;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceID;
        [MarshalAs(UnmanagedType.ByValTStr, SizeConst = 128)] public string DeviceKey; }
    public delegate bool EnumWindowsProc(IntPtr h, IntPtr lp);
    public delegate bool MonitorEnumProc(IntPtr m, IntPtr hdc, ref RECT r, IntPtr lp);
    [DllImport("user32.dll")] static extern bool EnumWindows(EnumWindowsProc cb, IntPtr lp);
    [DllImport("user32.dll")] static extern bool EnumDisplayMonitors(IntPtr hdc, IntPtr clip, MonitorEnumProc cb, IntPtr lp);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool GetMonitorInfo(IntPtr m, ref MONITORINFOEX mi);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern bool EnumDisplayDevices(string dev, int i, ref DISPLAY_DEVICE dd, int f);
    [DllImport("user32.dll")] static extern int GetWindowThreadProcessId(IntPtr h, out int pid);
    [DllImport("user32.dll")] static extern bool IsWindowVisible(IntPtr h);
    [DllImport("user32.dll")] static extern bool IsIconic(IntPtr h);
    [DllImport("user32.dll")] static extern bool GetWindowRect(IntPtr h, out RECT r);
    [DllImport("user32.dll", CharSet = CharSet.Unicode)] static extern int GetClassName(IntPtr h, StringBuilder s, int n);
    [DllImport("user32.dll")] static extern IntPtr SetThreadDpiAwarenessContext(IntPtr ctx);
    [DllImport("dwmapi.dll")] static extern int DwmGetWindowAttribute(IntPtr h, int a, out int v, int cb);
    [DllImport("winmm.dll")] static extern int timeBeginPeriod(int ms);
    [StructLayout(LayoutKind.Sequential)] struct POINT { public int X, Y; }
    [DllImport("user32.dll")] static extern bool GetCursorPos(out POINT p);
    [DllImport("user32.dll")] static extern IntPtr GetForegroundWindow();

    class Mon { public RECT rc; public string dev, adapter, monitor; public bool primary, isVirtual; }
    class Win { public string cls; public long firstMs = -1, visibleMs, cloakedMs, onRealMs, offTargetMs; public bool helper, everIconic; public RECT rect; public string on = ""; }
    static string virtualName;
    static Dictionary<string, string[]> names = new Dictionary<string, string[]>();   // GDI name -> {adapter, monitor}, cleared when the layout changes

    static string[] Names(string dev) {
        string[] n; if (names.TryGetValue(dev, out n)) return n;
        n = new string[] { "", "" };
        var dd = new DISPLAY_DEVICE(); dd.cb = Marshal.SizeOf(typeof(DISPLAY_DEVICE));
        for (int i = 0; EnumDisplayDevices(null, i, ref dd, 0); i++) {
            if (dd.DeviceName == dev) {
                n[0] = dd.DeviceString;
                var md = new DISPLAY_DEVICE(); md.cb = Marshal.SizeOf(typeof(DISPLAY_DEVICE));
                if (EnumDisplayDevices(dev, 0, ref md, 0)) n[1] = md.DeviceString;
                break;
            }
            dd.cb = Marshal.SizeOf(typeof(DISPLAY_DEVICE));
        }
        names[dev] = n; return n;
    }
    static string RS(RECT r) { return r.L + "," + r.T + "," + r.R + "," + r.B; }
    static List<Mon> ReadMonitors(out string sig, bool resolveNames) {
        var list = new List<Mon>(); var sb = new StringBuilder();
        EnumDisplayMonitors(IntPtr.Zero, IntPtr.Zero, delegate(IntPtr m, IntPtr hdc, ref RECT r, IntPtr lp) {
            var mi = new MONITORINFOEX(); mi.cbSize = Marshal.SizeOf(typeof(MONITORINFOEX)); GetMonitorInfo(m, ref mi);
            var x = new Mon(); x.rc = mi.rcMonitor; x.dev = mi.szDevice; x.primary = (mi.dwFlags & 1) != 0;
            list.Add(x); sb.Append(x.dev).Append('@').Append(RS(x.rc)).Append(x.primary ? "P;" : ";"); return true; }, IntPtr.Zero);
        sig = sb.ToString();
        if (resolveNames) {
            foreach (var x in list) {
                var n = Names(x.dev); x.adapter = n[0]; x.monitor = n[1];
                x.isVirtual = x.adapter.IndexOf(virtualName, StringComparison.OrdinalIgnoreCase) >= 0 || x.monitor.IndexOf(virtualName, StringComparison.OrdinalIgnoreCase) >= 0;
            }
        }
        return list;
    }
    static string J(string s) { if (s == null) return "null"; return "\"" + s.Replace("\\", "\\\\").Replace("\"", "\\\"").Replace("\r", " ").Replace("\n", " ") + "\""; }
    static string MonJ(Mon m) { return "{\"device\":" + J(m.dev) + ",\"rect\":[" + RS(m.rc) + "],\"primary\":" + (m.primary ? "true" : "false") + ",\"adapter\":" + J(m.adapter) + ",\"monitor\":" + J(m.monitor) + ",\"virtual\":" + (m.isVirtual ? "true" : "false") + "}"; }
    static string ListJ(List<Mon> l) { var parts = new List<string>(); foreach (var m in l) parts.Add(MonJ(m)); return "[" + string.Join(",", parts.ToArray()) + "]"; }
    static string MonLine(Mon m) { return "monitor " + m.dev + " " + RS(m.rc) + (m.primary ? " PRIMARY" : "") + " adapter='" + m.adapter + "' monitor='" + m.monitor + "'" + (m.isVirtual ? " [virtual]" : " [REAL]"); }
    static bool Overlap(RECT a, RECT b) { return a.L < b.R && b.L < a.R && a.T < b.B && b.T < a.B; }
    static bool Inside(RECT a, RECT b) { return a.L >= b.L && a.T >= b.T && a.R <= b.R && a.B <= b.B; }
    static string Utc() { return DateTime.UtcNow.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", System.Globalization.CultureInfo.InvariantCulture); }

    public static string Run(string outDir, string image, int forcePid, string vname, int waitStartS, int maxS) {
        SetThreadDpiAwarenessContext(new IntPtr(-4));   // per-monitor aware V2: physical pixels
        timeBeginPeriod(1);
        virtualName = vname;
        string txtPath = Path.Combine(outDir, "winprobe.txt");
        var tw = new StreamWriter(txtPath, false, new UTF8Encoding(false)); tw.AutoFlush = true;
        string sig; var mons = ReadMonitors(out sig, true);
        var startTopo = ListJ(mons);
        foreach (var m in mons) tw.WriteLine(MonLine(m));
        tw.WriteLine("READY " + Utc());
        File.WriteAllText(Path.Combine(outDir, "ready.txt"), Utc() + "\r\n");
        Process p = null; var t0 = Stopwatch.StartNew();
        string bn = Path.GetFileNameWithoutExtension(image);
        while (p == null && t0.ElapsedMilliseconds < waitStartS * 1000L) {
            if (File.Exists(Path.Combine(outDir, "stop"))) break;
            try {
                if (forcePid > 0) p = Process.GetProcessById(forcePid);
                else { var ps = Process.GetProcessesByName(bn); if (ps.Length > 0) p = ps[0]; }
            } catch { p = null; }
            if (p == null) Thread.Sleep(5);
        }
        if (p == null) {
            tw.WriteLine("the game did not start (waited " + (t0.ElapsedMilliseconds / 1000) + " s or stopped)"); tw.Close();
            File.WriteAllText(Path.Combine(outDir, "winprobe.json"), "{\"started\":false,\"image\":" + J(image) + ",\"topology_start\":" + startTopo + "}\r\n", new UTF8Encoding(false));
            return "no game";
        }
        IntPtr ph = IntPtr.Zero; try { ph = p.Handle; } catch { }   // keeps ExitCode readable after the exit
        int gamePid = p.Id;
        string startUtc = Utc();
        tw.WriteLine("game pid " + gamePid + " seen " + startUtc);
        var wins = new Dictionary<IntPtr, Win>();
        var changes = new List<string>();
        var sw = Stopwatch.StartNew();
        long samples = 0, realSamples = 0, offSamples = 0, realMsTotal = 0, cloakedMs = 0, longestReal = 0, realRunStart = -1, realRunLast = 0, prev = 0;
        string firstVisible = "null"; bool exited = false;
        // the game must not touch Liam's input: the real cursor newly at the exact centre of a monitor (an exclusive DirectInput
        // mouse recentres it, J13 PC run), and any time the game holds the foreground
        long recentres = 0, fgMs = 0; POINT lastCur; GetCursorPos(out lastCur);
        var handles = new List<IntPtr>();
        long limit = (long)maxS * 1000L;
        while (sw.ElapsedMilliseconds < limit) {
            long now = sw.ElapsedMilliseconds; long dt = now - prev; prev = now;
            string s2; var cur = ReadMonitors(out s2, false);
            if (s2 != sig) {
                names.Clear(); cur = ReadMonitors(out s2, true); sig = s2; mons = cur;
                changes.Add("{\"t_ms\":" + now + ",\"utc\":" + J(Utc()) + ",\"monitors\":" + ListJ(mons) + "}");
                tw.WriteLine("+" + now + " ms monitors changed:"); foreach (var m in mons) tw.WriteLine("    " + MonLine(m));
            }
            handles.Clear();
            EnumWindows(delegate(IntPtr h, IntPtr lp) { int pid; GetWindowThreadProcessId(h, out pid); if (pid == gamePid) handles.Add(h); return true; }, IntPtr.Zero);
            samples++;
            bool real = false, off = false, cloaked = false;
            foreach (var h in handles) {
                Win w; if (!wins.TryGetValue(h, out w)) { w = new Win(); var cb = new StringBuilder(64); GetClassName(h, cb, 64); w.cls = cb.ToString(); w.firstMs = now; wins[h] = w; }
                RECT r; GetWindowRect(h, out r); w.rect = r;
                bool vis = IsWindowVisible(h); int ck = 0; DwmGetWindowAttribute(h, 14, out ck, 4); bool ic = IsIconic(h);
                bool helper = (r.R - r.L) <= 1 && (r.B - r.T) <= 1; if (helper) w.helper = true;
                if (ic) w.everIconic = true;
                string on = ""; bool onReal = false, inVirt = false;
                foreach (var m in mons) if (Overlap(r, m.rc)) { on += (on.Length > 0 ? "+" : "") + m.dev + (m.isVirtual ? "(v)" : "(REAL)"); if (!m.isVirtual) onReal = true; }
                foreach (var m in mons) if (m.isVirtual && Inside(r, m.rc)) inVirt = true;
                if (on.Length == 0) on = "no monitor";
                bool shown = vis && ck == 0;
                if (vis) w.visibleMs += dt;
                if (vis && ck != 0) { w.cloakedMs += dt; cloaked = true; }
                if (!helper && shown && onReal) { w.onRealMs += dt; real = true; }
                if (!helper && shown && !ic && !inVirt) { w.offTargetMs += dt; off = true; }
                string st = (vis ? "visible" : "hidden") + (ck != 0 ? " cloaked" : "") + (ic ? " iconic" : "") + " rect " + RS(r) + " on " + on;
                if (w.on != st) {
                    tw.WriteLine("+" + now + " ms " + h.ToString("X") + " '" + w.cls + "'" + (helper ? " [helper]" : "") + " " + st);
                    w.on = st;
                }
                if (shown && !helper && firstVisible == "null") {
                    firstVisible = "{\"t_ms\":" + now + ",\"utc\":" + J(Utc()) + ",\"class\":" + J(w.cls) + ",\"rect\":[" + RS(r) + "],\"on\":" + J(on) + ",\"on_real_monitor\":" + (onReal ? "true" : "false") + "}";
                }
            }
            if (real) { realSamples++; realMsTotal += dt; if (realRunStart < 0) realRunStart = now - dt; realRunLast = now; if (realRunLast - realRunStart > longestReal) longestReal = realRunLast - realRunStart; } else realRunStart = -1;
            if (off) offSamples++;
            POINT cp; if (GetCursorPos(out cp)) {
                if (cp.X != lastCur.X || cp.Y != lastCur.Y) {
                    foreach (var m in mons) {
                        int cx = (m.rc.L + m.rc.R) / 2, cy = (m.rc.T + m.rc.B) / 2;
                        if (Math.Abs(cp.X - cx) <= 1 && Math.Abs(cp.Y - cy) <= 1) { recentres++; tw.WriteLine("+" + now + " ms CURSOR at the centre of " + m.dev + (m.isVirtual ? " (virtual)" : " (REAL)") + ": " + cp.X + "," + cp.Y); break; }
                    }
                }
                lastCur = cp;
            }
            int fgPid; GetWindowThreadProcessId(GetForegroundWindow(), out fgPid);
            if (fgPid == gamePid) { if (fgMs == 0) tw.WriteLine("+" + now + " ms the GAME has the foreground"); fgMs += Math.Max(dt, 1); }
            if (cloaked) cloakedMs += dt;
            if (p.HasExited) { exited = true; break; }
            Thread.Sleep(10);
        }
        long dur = sw.ElapsedMilliseconds;
        string exitCode = "null"; try { if (p.HasExited) exitCode = p.ExitCode.ToString(); } catch { }
        string sig3; var endMons = ReadMonitors(out sig3, true);
        var wl = new List<string>();
        foreach (var kv in wins) {
            var w = kv.Value;
            wl.Add("{\"hwnd\":" + J(kv.Key.ToString("X")) + ",\"class\":" + J(w.cls) + ",\"first_seen_ms\":" + w.firstMs + ",\"helper_1x1\":" + (w.helper ? "true" : "false") + ",\"visible_ms\":" + w.visibleMs + ",\"cloaked_ms\":" + w.cloakedMs + ",\"visible_on_real_ms\":" + w.onRealMs + ",\"visible_off_target_ms\":" + w.offTargetMs + ",\"ever_iconic\":" + (w.everIconic ? "true" : "false") + ",\"last_rect\":[" + RS(w.rect) + "],\"last_state\":" + J(w.on) + "}");
        }
        var js = new StringBuilder();
        js.Append("{\"started\":true,\"image\":").Append(J(image)).Append(",\"pid\":").Append(gamePid).Append(",\"game_seen_utc\":").Append(J(startUtc)).Append(",\"ended_utc\":").Append(J(Utc()));
        js.Append(",\"exited\":").Append(exited ? "true" : "false").Append(",\"exit_code\":").Append(exitCode);
        js.Append(",\"samples\":").Append(samples).Append(",\"duration_ms\":").Append(dur);
        js.Append(",\"longest_visible_on_real_ms\":").Append(realSamples > 0 ? Math.Max(1, longestReal) : 0);
        js.Append(",\"visible_on_real_ms_total\":").Append(realMsTotal).Append(",\"visible_on_real_samples\":").Append(realSamples);
        js.Append(",\"visible_off_target_count\":").Append(offSamples).Append(",\"cloaked_ms\":").Append(cloakedMs);
        js.Append(",\"cursor_recentres\":").Append(recentres).Append(",\"game_foreground_ms\":").Append(fgMs);
        js.Append(",\"monitor_changes\":[").Append(string.Join(",", changes.ToArray())).Append("]");
        js.Append(",\"first_visible\":").Append(firstVisible);
        js.Append(",\"windows\":[").Append(string.Join(",", wl.ToArray())).Append("]");
        js.Append(",\"topology_start\":").Append(startTopo).Append(",\"topology_end\":").Append(ListJ(endMons)).Append("}");
        File.WriteAllText(Path.Combine(outDir, "winprobe.json"), js.ToString() + "\r\n", new UTF8Encoding(false));
        tw.WriteLine("samples=" + samples + " duration_ms=" + dur + " exited=" + exited + " exit_code=" + exitCode);
        tw.WriteLine("LONGEST_VISIBLE_ON_REAL_MS=" + (realSamples > 0 ? Math.Max(1, longestReal) : 0));
        tw.WriteLine("VISIBLE_ON_REAL_MS_TOTAL=" + realMsTotal + " SAMPLES=" + realSamples + "/" + samples);
        tw.WriteLine("VISIBLE_OFF_TARGET_COUNT=" + offSamples);
        tw.WriteLine("CLOAKED_MS=" + cloakedMs);
        tw.WriteLine("MONITOR_CHANGES=" + changes.Count);
        tw.WriteLine("DONE " + Utc());
        tw.Close();
        return "done";
    }
}
'@
[void][NWinProbe]::Run($OutDir, $Image, $ProcessId, $VirtualName, $WaitStartS, $MaxS)
