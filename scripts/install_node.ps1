$ErrorActionPreference = 'Stop'
$version = '24.22.2'
$archiveName = "node-v$version-win-x64.zip"
$runtimeRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\.runtime'))
$nodeDirectory = Join-Path $runtimeRoot 'node'
$extractedDirectory = Join-Path $runtimeRoot "node-v$version-win-x64"
foreach ($target in @($nodeDirectory, $extractedDirectory)) {
    if (-not [IO.Path]::GetFullPath($target).StartsWith($runtimeRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::OrdinalIgnoreCase)) { throw 'Node installation target is outside .runtime.' }
}
if (Test-Path -LiteralPath $nodeDirectory) {
    $executable = Join-Path $nodeDirectory 'node.exe'
    if (-not (Test-Path -LiteralPath $executable)) { throw 'Existing .runtime/node is incomplete; it has been preserved.' }
    $installed = & $executable --version
    if ($LASTEXITCODE -ne 0 -or $installed -ne "v$version") { throw 'Existing .runtime/node has another version; it has been preserved.' }
    Write-Host "Node v$version already installed."
    return $nodeDirectory
}
if (Test-Path -LiteralPath $extractedDirectory) { throw 'Existing staged Node directory has been preserved; inspect it before retrying.' }
New-Item -ItemType Directory -Path $runtimeRoot -Force | Out-Null
$archive = Join-Path $runtimeRoot $archiveName
$checksums = Join-Path $runtimeRoot "SHASUMS256-v$version.txt"
$baseUrl = "https://nodejs.org/dist/v$version"
try {
    Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/SHASUMS256.txt" -OutFile $checksums
    $entries = @(Get-Content -LiteralPath $checksums | Where-Object { $_ -match ('^[a-fA-F0-9]{64}\s+' + [regex]::Escape($archiveName) + '$') })
    if ($entries.Count -ne 1) { throw 'Official Node checksum entry is missing or ambiguous.' }
    Invoke-WebRequest -UseBasicParsing -Uri "$baseUrl/$archiveName" -OutFile $archive
    $sha256 = [Security.Cryptography.SHA256]::Create()
    try {
        $stream = [IO.File]::OpenRead($archive)
        try {
            $actualHash = [BitConverter]::ToString($sha256.ComputeHash($stream)).Replace('-', '')
        } finally {
            $stream.Dispose()
        }
    } finally {
        $sha256.Dispose()
    }
    if ($actualHash -ne $entries[0].Substring(0, 64)) { throw 'Node archive SHA256 verification failed.' }
    Expand-Archive -LiteralPath $archive -DestinationPath $runtimeRoot
    $installed = & (Join-Path $extractedDirectory 'node.exe') --version
    if ($LASTEXITCODE -ne 0 -or $installed -ne "v$version") { throw 'Downloaded Node version does not match the pinned version.' }
    if (Test-Path -LiteralPath $nodeDirectory) { throw 'Existing .runtime/node has been preserved; installation stopped.' }
    Move-Item -LiteralPath $extractedDirectory -Destination $nodeDirectory
    Write-Host "Node v$version SHA256 $actualHash"
    return $nodeDirectory
} finally {
    Remove-Item -LiteralPath $archive, $checksums -Force -ErrorAction SilentlyContinue
}
