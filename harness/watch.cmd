@echo off
rem purpose: launcher loop for the watcher: restarts watcher.ps1 after a crash or a restart request, stops when told to or when another watcher owns the root
rem usage: started at logon by the scheduled task the kit names (Install watcher.cmd); by hand: double-click it. Optional arguments are passed on (-Root <dir> -Adapter <file>)
rem when: never edit it while it runs (cmd re-reads batch files from disk): edit watcher.ps1 and send an update or restart job instead
rem not-a-verb: a Windows batch launcher that runs on the PC
rem watcher.ps1 exit codes: 3 restart, 4 restart this launcher too, 10 another watcher owns the root, 11 stopped on request. Anything else (a crash) restarts after 4 s.
title watcher %~dp0
cd /d "%~dp0"
:loop
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0watcher.ps1" %*
if errorlevel 10 exit /b 0
if errorlevel 4 (start "" "%~f0" %* & exit /b 0)
ping -n 4 127.0.0.1 >nul
goto loop
