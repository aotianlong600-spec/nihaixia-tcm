$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$nodeDirectory = & (Join-Path $PSScriptRoot 'scripts\install_node.ps1')
$env:PATH = "$nodeDirectory;$env:PATH"
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & python.exe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt --cache-dir (Join-Path $PSScriptRoot '.cache\pip')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Push-Location 'ai-bridge'
try { & npm.cmd ci --ignore-scripts --cache (Join-Path $PSScriptRoot '.cache\npm'); if ($LASTEXITCODE -ne 0) { throw 'Model bridge installation failed.' } } finally { Pop-Location }
Push-Location 'frontend'
try {
    & npm.cmd ci --ignore-scripts --cache (Join-Path $PSScriptRoot '.cache\npm')
    if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
    & npm.cmd run build
    if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
} finally { Pop-Location }
Write-Output 'Setup complete. Run start.cmd.'
