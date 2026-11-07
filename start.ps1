param([string]$DataDirectory = (Join-Path $PSScriptRoot 'data'), [int]$Port=8767, [switch]$NoBrowser, [switch]$Lan)
$ErrorActionPreference = 'Stop'
$serviceUrl = "http://127.0.0.1:$Port"
$dataPath = [System.IO.Path]::GetFullPath($DataDirectory)
New-Item -ItemType Directory -Path $dataPath -Force | Out-Null
$health = $null
try { $health = Invoke-RestMethod "$serviceUrl/api/status" -TimeoutSec 2 } catch { }
if ($health -and $health.app_id -ne 'nihaixia-clinical-engine') { throw 'Port 8765 is occupied by another service.' }
if ($health -and $Lan -and -not $health.lan_enabled) { throw 'Service is running in local mode. Stop it, then run start-lan.cmd.' }
if (-not $health) {
    $pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
    & $pythonPath -c 'import fastapi, uvicorn, pydantic, pdfplumber, pypdfium2, cryptography, multipart'
    if ($LASTEXITCODE -ne 0) { throw 'Dependencies missing. Run setup.cmd first.' }
    if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot 'frontend\dist\index.html'))) { throw 'Frontend not built. Run setup.cmd first.' }
    $runScript = Join-Path $PSScriptRoot 'scripts\run.py'
    $arguments = @('-u', ('"' + $runScript + '"'), '--data-dir', ('"' + $dataPath + '"'),'--port',"$Port")
    $knowledgePack = Join-Path $PSScriptRoot 'knowledge'
    if (Test-Path -LiteralPath (Join-Path $knowledgePack 'manifest.json')) {
        $arguments += @('--knowledge-pack',('"'+$knowledgePack+'"'))
    }
    if ($Lan) {
        if (-not (Test-Path -LiteralPath (Join-Path $dataPath 'access.json'))) { throw 'Set an access password on the local Settings page first.' }
        $arguments += '--lan'
    }
    $server = Start-Process -FilePath $pythonPath -ArgumentList $arguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $dataPath 'server.stdout.log') -RedirectStandardError (Join-Path $dataPath 'server.stderr.log')
    Set-Content -LiteralPath (Join-Path $dataPath 'server.pid') -Value $server.Id -Encoding ascii
    for ($attempt = 0; $attempt -lt 60; $attempt++) {
        try { $health = Invoke-RestMethod "$serviceUrl/api/status" -TimeoutSec 1; break } catch { Start-Sleep -Milliseconds 250 }
        if ($server.HasExited) { throw "Service exited. Inspect $dataPath\server.stderr.log" }
    }
    if (-not $health -or $health.app_id -ne 'nihaixia-clinical-engine') { throw 'Service did not become ready.' }
}
Write-Output "Workbench ready: $serviceUrl (personal assistant)"
if ($Lan) {
    $pythonPath = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $pythonPath)) { $pythonPath = (Get-Command python.exe -ErrorAction Stop).Source }
    $lanInfo = & $pythonPath (Join-Path $PSScriptRoot 'scripts\prepare_lan.py') --data-dir $dataPath | ConvertFrom-Json
    $lanInfo.addresses | ForEach-Object { Write-Output "LAN: $_" }
    Write-Output "CA SHA256: $($lanInfo.ca_sha256)"
}
if (-not $NoBrowser) { Start-Process $serviceUrl }
