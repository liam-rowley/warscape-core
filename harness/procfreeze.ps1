# purpose: suspend or resume every thread of a process (NtSuspendProcess / NtResumeProcess): the way to force a hang for the watchdog test, without killing anything
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File procfreeze.ps1 -ProcessId <pid> -Mode suspend|resume   (as a ps1 job: "#job type=ps1 owner=<lock owner>" then & "<root>\src\procfreeze.ps1" ...)
# when: PC test of the hang watchdog (suspend the game, expect a minidump, an archive under runs\ and a kill); resume to undo a test that was not meant to hang
# not-a-verb: runs on the PC under Windows PowerShell 5.1, outside the repo checkout
param([Parameter(Mandatory = $true)][int]$ProcessId, [Parameter(Mandatory = $true)][ValidateSet('suspend', 'resume')][string]$Mode)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class ProcFreeze {
    [DllImport("ntdll.dll")] static extern int NtSuspendProcess(IntPtr h);
    [DllImport("ntdll.dll")] static extern int NtResumeProcess(IntPtr h);
    public static int Do(int pid, bool suspend) {
        using (var p = System.Diagnostics.Process.GetProcessById(pid)) { return suspend ? NtSuspendProcess(p.Handle) : NtResumeProcess(p.Handle); }
    }
}
'@
$rc = [ProcFreeze]::Do($ProcessId, ($Mode -eq 'suspend'))
Write-Output "$Mode pid ${ProcessId}: NTSTATUS $rc"
exit $(if ($rc -eq 0) { 0 } else { 1 })
