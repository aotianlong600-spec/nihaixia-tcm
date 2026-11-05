[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$CaCertificate,

    [string]$SdkDirectory = "D:/android",

    [string]$JavaHome,

    [string]$OutputDirectory
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$scriptRoot = $PSScriptRoot
if ([string]::IsNullOrWhiteSpace($scriptRoot)) {
    $scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
}
$repoRoot = Split-Path -Parent $scriptRoot
$androidRoot = Join-Path $repoRoot "android"
$wrapperDir = Join-Path $androidRoot "gradle/wrapper"
$wrapperProperties = Join-Path $wrapperDir "gradle-wrapper.properties"
$wrapperJar = Join-Path $wrapperDir "gradle-wrapper.jar"
$rawDir = Join-Path $androidRoot "app/src/main/res/raw"
$caDestination = Join-Path $rawDir "ca_cert.pem"

function Get-Sha256([string]$LiteralPath) {
    $stream = [System.IO.File]::OpenRead($LiteralPath)
    $algorithm = [System.Security.Cryptography.SHA256]::Create()
    try { return [BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-', '').ToLowerInvariant() }
    finally { $algorithm.Dispose(); $stream.Dispose() }
}

function Resolve-Jdk17 {
    param(
        [string]$RequestedJavaHome,
        [string]$SdkPath
    )

    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($RequestedJavaHome)) {
        $candidates.Add($RequestedJavaHome)
    } else {
        if (-not [string]::IsNullOrWhiteSpace($env:JAVA_HOME)) {
            $candidates.Add($env:JAVA_HOME)
        }
        $candidates.Add((Join-Path $SdkPath "jbr"))
        $candidates.Add((Join-Path $SdkPath "jdk-17"))
        $candidates.Add((Join-Path $SdkPath "jdk17"))
        $candidates.Add((Join-Path $SdkPath "openjdk-17"))
        if (Test-Path -LiteralPath $SdkPath -PathType Container) {
            Get-ChildItem -LiteralPath $SdkPath -Directory -ErrorAction SilentlyContinue |
                Where-Object { $_.Name -match "^(jdk|jbr|openjdk).*17" } |
                ForEach-Object { $candidates.Add($_.FullName) }
        }
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        $javaExe = Join-Path $candidate "bin/java.exe"
        $javacExe = Join-Path $candidate "bin/javac.exe"
        if (-not (Test-Path -LiteralPath $javaExe -PathType Leaf) -or -not (Test-Path -LiteralPath $javacExe -PathType Leaf)) {
            continue
        }
        $previousPreference = $ErrorActionPreference
        try {
            $ErrorActionPreference = 'Continue' # Java prints its version on stderr in Windows PowerShell 5.
            $versionText = (& $javaExe -version 2>&1 | Out-String)
        } finally { $ErrorActionPreference = $previousPreference }
        if ($versionText -match 'version "17\.') {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "JDK 17 was not found. Pass -JavaHome <path-to-jdk17> or install JDK 17 under $SdkPath. The script does not change global JAVA_HOME."
}

function Import-PublicCaCertificate {
    param([string]$SourcePath)

    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "CA certificate not found: $SourcePath"
    }
    $pemText = Get-Content -LiteralPath $SourcePath -Raw
    if ($pemText -imatch "PRIVATE KEY") {
        throw "Refusing to use a PEM containing a private key. Pass the PUBLIC CA certificate only."
    }

    $beginMatches = [regex]::Matches($pemText, "-----BEGIN CERTIFICATE-----")
    $endMatches = [regex]::Matches($pemText, "-----END CERTIFICATE-----")
    if ($beginMatches.Count -ne 1 -or $endMatches.Count -ne 1) {
        throw "Expected exactly one PEM CERTIFICATE block (public CA only)."
    }

    $certMatch = [regex]::Match(
        $pemText,
        "-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----",
        [System.Text.RegularExpressions.RegexOptions]::Singleline)
    if (-not $certMatch.Success) {
        throw "No PEM CERTIFICATE block found."
    }

    $base64 = $certMatch.Value -replace "-----BEGIN CERTIFICATE-----", ""
    $base64 = $base64 -replace "-----END CERTIFICATE-----", ""
    $base64 = $base64 -replace "\s", ""
    try {
        $der = [Convert]::FromBase64String($base64)
    } catch {
        throw "The PEM certificate is not valid base64."
    }

    $certificate = New-Object System.Security.Cryptography.X509Certificates.X509Certificate2
    try {
        $certificate.Import($der)
        if ($certificate.HasPrivateKey) {
            throw "Refusing to use a certificate that contains a private key."
        }
        $basicConstraints = $certificate.Extensions |
            Where-Object { $_ -is [System.Security.Cryptography.X509Certificates.X509BasicConstraintsExtension] } |
            Select-Object -First 1
        if ($null -eq $basicConstraints -or -not $basicConstraints.CertificateAuthority) {
            throw "The certificate is not a CA certificate (basicConstraints CA=true is required)."
        }
        if ($certificate.NotAfter -le (Get-Date)) {
            throw "The CA certificate is expired."
        }
    } finally {
        $certificate.Dispose()
    }

    return $certMatch.Value + [Environment]::NewLine
}

if (-not (Test-Path -LiteralPath $androidRoot -PathType Container)) {
    throw "Android project directory not found: $androidRoot"
}
if (-not (Test-Path -LiteralPath $SdkDirectory -PathType Container)) {
    throw "Android SDK directory not found: $SdkDirectory"
}
$sdkPath = (Resolve-Path -LiteralPath $SdkDirectory).Path
$platform35 = Join-Path $sdkPath "platforms/android-35"
if (-not (Test-Path -LiteralPath $platform35 -PathType Container)) {
    throw "Android SDK platform 35 is missing under $sdkPath. Install it in Android Studio; this script does not accept SDK licenses."
}

if (-not (Test-Path -LiteralPath $wrapperProperties -PathType Leaf)) { throw 'Missing gradle-wrapper.properties.' }
$wrapperText = Get-Content -LiteralPath $wrapperProperties -Raw
if ($wrapperText -notmatch 'gradle-8\.9-bin\.zip' -or $wrapperText -notmatch 'distributionSha256Sum=d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab') { throw 'Unexpected Gradle distribution or checksum.' }
if (-not (Test-Path -LiteralPath $wrapperJar -PathType Leaf)) { throw 'Missing wrapper JAR; restore it from the source repository.' }
if ((Get-Sha256 $wrapperJar) -ne '498495120a03b9a6ab5d155f5de3c8f0d986a449153702fb80fc80e134484f17') { throw 'Unexpected Gradle wrapper JAR checksum.' }

$jdkPath = Resolve-Jdk17 -RequestedJavaHome $JavaHome -SdkPath $sdkPath

$pem = Import-PublicCaCertificate -SourcePath $CaCertificate
if (-not (Test-Path -LiteralPath $rawDir -PathType Container)) {
    New-Item -ItemType Directory -Path $rawDir -Force | Out-Null
}
$utf8NoBom = New-Object -TypeName System.Text.UTF8Encoding -ArgumentList $false
[System.IO.File]::WriteAllText($caDestination, $pem, $utf8NoBom)

# Process-local only: no global environment changes, no SDK license acceptance.
$env:JAVA_HOME = $jdkPath
$env:ANDROID_HOME = $sdkPath
$env:ANDROID_SDK_ROOT = $sdkPath
$env:GRADLE_USER_HOME = Join-Path $androidRoot ".gradle-user-home"
$env:ANDROID_USER_HOME = Join-Path $androidRoot ".android-user-home"
$env:Path = (Join-Path $jdkPath "bin") + [System.IO.Path]::PathSeparator + $env:Path

Write-Host "Using JDK: $jdkPath"
Write-Host "Using Android SDK: $sdkPath"
Write-Host "Using Gradle user home: $env:GRADLE_USER_HOME"
Write-Host "Using Android user home: $env:ANDROID_USER_HOME"
Write-Host "CA resource: $caDestination"

Push-Location $androidRoot
try {
    & (Join-Path $androidRoot "gradlew.bat") "testDebugUnitTest" "assembleDebug" "--no-daemon" "--console=plain"
    if ($LASTEXITCODE -ne 0) {
        throw "Gradle failed with exit code $LASTEXITCODE."
    }
} finally {
    Pop-Location
}

$apkPath = Join-Path $androidRoot "app/build/outputs/apk/debug/app-debug.apk"
if (-not (Test-Path -LiteralPath $apkPath -PathType Leaf)) {
    throw "Debug APK was not produced at $apkPath"
}

if (-not [string]::IsNullOrWhiteSpace($OutputDirectory)) {
    if (-not [System.IO.Path]::IsPathRooted($OutputDirectory)) {
        $OutputDirectory = Join-Path $repoRoot $OutputDirectory
    }
    New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null
    $outputPath = (Resolve-Path -LiteralPath $OutputDirectory).Path
    $apkDestination = Join-Path $outputPath "nihaixia-workbench-debug.apk"
    Copy-Item -LiteralPath $apkPath -Destination $apkDestination -Force
    $apkPath = $apkDestination
}

$hash = Get-Sha256 $apkPath
Write-Host "APK: $apkPath"
Write-Host "APK SHA256: $hash"
