@echo off
rem purpose: turn WER LocalDumps for the game's exe off again (removes only its own registry subkey); asks for admin rights once
rem usage: double-click it
rem when: when crash dumps are no longer wanted
rem not-a-verb: a Windows double-click wrapper around wer_localdumps.ps1
powershell -NoProfile -ExecutionPolicy Bypass -Command "Start-Process -Verb RunAs -Wait -FilePath powershell.exe -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-Command','& ''%~dp0wer_localdumps.ps1'' -Mode disable *> ''%TEMP%\wsp_wer_disable.txt'''"
type "%TEMP%\wsp_wer_disable.txt"
echo.
pause
