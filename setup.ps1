$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & python.exe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
& node.exe -e 'const [a,b]=process.versions.node.split(".").map(Number);if(a<22||(a===22&&b<19))process.exit(1)'
if ($LASTEXITCODE -ne 0) { throw 'Node 22.19 or later is required.' }
Push-Location 'ai-bridge'
try { & npm.cmd ci --ignore-scripts; if ($LASTEXITCODE -ne 0) { throw 'Model bridge installation failed.' } } finally { Pop-Location }
if (-not (Test-Path -LiteralPath 'frontend\dist\index.html')) {
    Push-Location 'frontend'
    try {
        & npm.cmd ci --ignore-scripts
        if ($LASTEXITCODE -ne 0) { throw 'Frontend dependency installation failed.' }
        & npm.cmd run build
        if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
    } finally { Pop-Location }
}
Write-Output 'Setup complete. Run start.cmd.'
