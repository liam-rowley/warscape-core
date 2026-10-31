@echo off
rem purpose: turn on WER LocalDumps (full crash dumps, out of process) for the game's exe only (its proxy adapter's identity.json); asks for admin rights once
rem usage: double-click it (Liam, once per PC); undo with "Disable crash dumps.cmd"
rem when: before the first PC test of the proxy; the dumps go to %LOCALAPPDATA%\CrashDumps\<mod_dir>
rem not-a-verb: a Windows double-click wrapper around wer_localdumps.ps1
echo Enabling crash dumps for the game's exe (a Windows admin prompt will appear)...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -Verb RunAs -Wait -FilePath powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command','& ''%~dp0wer_localdumps.ps1'' -Mode enable *> ''%TEMP%\wsp_wer_enable.txt'''"
type "%TEMP%\wsp_wer_enable.txt"
echo.
pause
