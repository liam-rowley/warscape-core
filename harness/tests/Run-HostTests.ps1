# purpose: run the harness host test suites (unit, integration or all) under the PowerShell that launches it and exit non-zero on any failure
# usage: powershell -NoProfile -ExecutionPolicy Bypass -File Run-HostTests.ps1 [-Suite unit|integration|all] [-Repo <repo root>] [-Only <case-name regex>] [-Repeat <n>]
# when: CI job harness-windows runs it with -Suite all under Windows PowerShell 5.1; locally -Suite unit works under pwsh on Linux
# not-a-verb: a PowerShell test runner, not a repo operation
# -Only and -Repeat go to the integration suite (the flaky-case chaser, J19); the unit suite always runs whole, it takes seconds.
param([ValidateSet('unit', 'integration', 'all')][string]$Suite = 'all', [string]$Repo = '', [string]$Only = '', [ValidateRange(1, 1000)][int]$Repeat = 1)
if (-not $Repo) { $Repo = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..')) }
$rc = 0
if ($Suite -in 'unit', 'all') { & (Join-Path $PSScriptRoot 'Test-Unit.ps1') -Repo $Repo; if ($LASTEXITCODE -ne 0) { $rc = 1 } }
if ($Suite -in 'integration', 'all') { & (Join-Path $PSScriptRoot 'Test-Integration.ps1') -Repo $Repo -Only $Only -Repeat $Repeat; if ($LASTEXITCODE -ne 0) { $rc = 1 } }
exit $rc
