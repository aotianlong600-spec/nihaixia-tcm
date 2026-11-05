param([string]$DataDirectory = (Join-Path $PSScriptRoot 'data'), [switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$serviceUrl = 'http://127.0.0.1:8765'
$dataPath = [System.IO.Path]::GetFullPath($DataDirectory)
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
$health = $null
try { $health = Invoke-RestMethod "$serviceUrl/api/status" -TimeoutSec 2 } catch { }
if ($health -and $health.app_id -ne 'nihaixia-clinical-engine') { throw 'Port 8765 is occupied by another service.' }
if (-not $health) {
    $pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
    & $pythonPath -c 'import fastapi, uvicorn, pydantic, pdfplumber, pypdfium2, cryptography, multipart'
    if ($LASTEXITCODE -ne 0) { throw 'Dependencies missing. Run setup.cmd first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend\dist\index.html'))) { throw 'Frontend not built. Run setup.cmd first.' }
    $runScript = Join-Path $PSScriptRoot 'scripts\run.py'
    $arguments = @('-u', ('"' + $runScript + '"'), '--data-dir', ('"' + $dataPath + '"'))
    $server = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataPath 'server.stdout.log') -RedirectStandardError (Join-Path $dataPath 'server.stderr.log')
    Set-Content -LiteralPath (Join-Path $dataPath 'server.pid') -Value $server.Id -Encoding ascii
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try { $health = Invoke-RestMethod "$serviceUrl/api/status" -TimeoutSec 1; break } catch { Start-Sleep -Milliseconds 250 }
        if ($server.HasExited) { throw "Service exited. Inspect $dataPath\server.stderr.log" }
    }
    if (-not $health -or $health.app_id -ne 'nihaixia-clinical-engine') { throw 'Service did not become ready.' }
}
Write-Output "Workbench ready: $serviceUrl (simulation only)"
if (-not $NoBrowser) { Start-Process $serviceUrl }
