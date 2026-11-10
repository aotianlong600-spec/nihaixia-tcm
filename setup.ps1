$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
if (-not (Test-Path -LiteralPath '.venv\Scripts\python.exe')) {
    & python.exe -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw 'Python 3.11 or later is required.' }
}
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.txt --cache-dir (Join-Path $PSScriptRoot '.cache\pip')
if ($LASTEXITCODE -ne 0) { throw 'Python dependency installation failed.' }
Write-Output 'Setup complete. Run 启动离线网页.cmd, then open http://127.0.0.1:8767/api/status'
