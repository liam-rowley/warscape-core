@echo off
rem purpose: double-click installer for the watcher: copies the kit's harness files into the watcher root (sha256 checked) and registers the logon task the kit names (manifest task_name; no admin rights)
rem usage: double-click it in the harness kit folder (Liam, once per PC); undo with "Uninstall watcher.cmd" from the same kit; options for the PowerShell script: install.ps1 -Root <dir> -NoTask -NoStart
rem when: first install of the watcher on a PC; later updates go through the watcher's update job (no double-click)
rem not-a-verb: a Windows double-click wrapper around install.ps1
echo Installing the watcher from this kit ...
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1" -Kit "%~dp0."
echo.
pause
