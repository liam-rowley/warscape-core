@echo off
rem purpose: double-click uninstaller for the watcher: stops it, removes the logon task and moves the installed harness files to _to_delete (jobs, logs and runs are kept)
rem usage: double-click it in the harness kit folder; the PowerShell script is install.ps1 -Uninstall
rem when: when the watcher should leave the PC; nothing in the game folder is touched
rem not-a-verb: a Windows double-click wrapper around install.ps1
echo Uninstalling the watcher of this kit ...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Kit "%~dp0." -Uninstall
echo.
pause
