# purpose: write an out-of-process minidump of one running process with MiniDumpWriteDump (the watcher calls it on a hang, with a PowerShell of the TARGET's bitness)
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File dump.ps1 -ProcessId <pid> -Out <file.dmp> [-Type 0x1165]   (32-bit game: run it with C:\Windows\SysWOW64\WindowsPowerShell\v1.0\powershell.exe)
# when: by hand to dump a stuck process; normally only the watcher's hang handler runs it
# not-a-verb: runs on the PC under Windows PowerShell 5.1, outside the repo checkout
param([Parameter(Mandatory = $true)][int]$ProcessId, [Parameter(Mandatory = $true)][string]$Out, [string]$Type = '0x1165')
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.IO;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;
public static class WatcherMiniDump {
    [DllImport("dbghelp.dll", SetLastError = true)]
    static extern bool MiniDumpWriteDump(IntPtr hProcess, uint processId, SafeFileHandle hFile, uint dumpType, IntPtr exceptionParam, IntPtr userStreamParam, IntPtr callbackParam);
    public static string Write(int pid, string path, uint type) {
        using (var p = System.Diagnostics.Process.GetProcessById(pid))
        using (var fs = new FileStream(path, FileMode.Create, FileAccess.ReadWrite, FileShare.None)) {
            bool ok = MiniDumpWriteDump(p.Handle, (uint)pid, fs.SafeFileHandle, type, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero);
            if (!ok) return "MiniDumpWriteDump failed, win32 error " + Marshal.GetLastWin32Error();
        }
        return null;
    }
}
'@
$t = [Convert]::ToUInt32($Type.Replace('0x', ''), 16)
$err = [WatcherMiniDump]::Write($ProcessId, $Out, $t)
if ($err) { Write-Output $err; exit 1 }
Write-Output ("minidump written: {0} ({1} bytes, pid {2}, {3}-bit powershell)" -f $Out, (Get-Item -LiteralPath $Out).Length, $ProcessId, $(if ([Environment]::Is64BitProcess) { 64 } else { 32 }))
exit 0
