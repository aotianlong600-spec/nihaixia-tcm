param([string]$DataDirectory = (Join-Path $PSScriptRoot 'data'))
$ErrorActionPreference = 'Stop'
$pidPath = Join-Path ([System.IO.Path]::GetFullPath($DataDirectory)) 'server.pid'
if (-not (Test-Path -LiteralPath $pidPath)) { Write-Output 'No managed service PID found.'; exit 0 }
$serverProcessId = [int](Get-Content -LiteralPath $pidPath)
$processInfo = Get-CimInstance Win32_Process -Filter "ProcessId=$serverProcessId" -ErrorAction SilentlyContinue
$expectedScript = Join-Path $PSScriptRoot 'scripts\run.py'
if ($processInfo -and $processInfo.CommandLine.IndexOf($expectedScript, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
    Stop-Process -Id $serverProcessId
    Remove-Item -LiteralPath $pidPath
    Write-Output 'Workbench stopped.'
} elseif ($processInfo) { throw 'PID belongs to another process; refusing to stop it.' }
