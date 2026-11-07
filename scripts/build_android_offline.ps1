[CmdletBinding()]
param(
    [string]$SdkDirectory = "D:/android",

    [string]$JavaHome,

    [string]$BuildPython,

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
$cacheRoot = Join-Path $repoRoot ".cache"
$wrapperDir = Join-Path $androidRoot "gradle/wrapper"
$wrapperProperties = Join-Path $wrapperDir "gradle-wrapper.properties"
$wrapperJar = Join-Path $wrapperDir "gradle-wrapper.jar"

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
        if (-not (Test-Path -LiteralPath $javaExe -PathType Leaf) -or
            -not (Test-Path -LiteralPath $javacExe -PathType Leaf)) {
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

function Test-Python311([string]$Exe) {
    $previousPreference = $ErrorActionPreference
    try {
        $ErrorActionPreference = 'Continue'
        $version = (& $Exe -c "import sys; print('%d.%d' % sys.version_info[:2])" 2>&1 | Out-String).Trim()
    } catch {
        return $false
    } finally { $ErrorActionPreference = $previousPreference }
    return $version -eq "3.11"
}

function Resolve-Python311([string]$Requested) {
    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($Requested)) {
        $candidates.Add($Requested)
    } else {
        $candidates.Add((Join-Path $env:SystemDrive "Python311/python.exe"))
        $candidates.Add("D:/Python311/python.exe")
        $candidates.Add("D:/Python3.11/python.exe")
        $candidates.Add("D:/Python/python.exe")
        foreach ($name in @("python.exe", "python3.exe", "python3.11.exe")) {
            $command = Get-Command $name -ErrorAction SilentlyContinue
            if ($null -ne $command -and -not [string]::IsNullOrWhiteSpace($command.Source)) {
                $candidates.Add($command.Source)
            }
        }
    }

    foreach ($candidate in ($candidates | Select-Object -Unique)) {
        if ([string]::IsNullOrWhiteSpace($candidate) -or
            -not (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            continue
        }
        if (Test-Python311 $candidate) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw "Python 3.11 was not found. Pass -BuildPython <path-to-python3.11.exe>. This script does not change global PATH or install Python."
}

if (-not (Test-Path -LiteralPath $androidRoot -PathType Container)) {
    throw "Android project directory not found: $androidRoot"
}
if (-not (Test-Path -LiteralPath (Join-Path $androidRoot "gradlew.bat") -PathType Leaf)) {
    throw "Missing gradlew.bat in $androidRoot."
}
if (-not (Test-Path -LiteralPath $SdkDirectory -PathType Container)) {
    throw "Android SDK directory not found: $SdkDirectory"
}
$sdkPath = (Resolve-Path -LiteralPath $SdkDirectory).Path
$platform35 = Join-Path $sdkPath "platforms/android-35"
if (-not (Test-Path -LiteralPath $platform35 -PathType Container)) {
    throw "Android SDK platform 35 is missing under $sdkPath. Install it in Android Studio; this script does not accept SDK licenses."
}

$frontendIndex = Join-Path $repoRoot "frontend/dist/index.html"
if (-not (Test-Path -LiteralPath $frontendIndex -PathType Leaf)) {
    throw "frontend/dist/index.html is missing. Build the Vue bundle first; the APK must not depend on a CDN."
}
$knowledgeSource = Join-Path $repoRoot "knowledge"
$bundledKnowledge = Join-Path $androidRoot "app/src/main/assets/knowledge"
if (-not (Test-Path -LiteralPath $knowledgeSource -PathType Container) -and
    -not (Test-Path -LiteralPath $bundledKnowledge -PathType Container)) {
    throw "No knowledge pack found at $knowledgeSource or $bundledKnowledge. Copy the packaged knowledge assets before building."
}

if (-not (Test-Path -LiteralPath $wrapperProperties -PathType Leaf)) { throw 'Missing gradle-wrapper.properties.' }
$wrapperText = Get-Content -LiteralPath $wrapperProperties -Raw
if ($wrapperText -notmatch 'gradle-8\.9-bin\.zip' -or
    $wrapperText -notmatch 'distributionSha256Sum=d725d707bfabd4dfdc958c624003b3c80accc03f7037b5122c4b1d0ef15cecab') {
    throw 'Unexpected Gradle distribution or checksum.'
}
if (-not (Test-Path -LiteralPath $wrapperJar -PathType Leaf)) {
    throw 'Missing wrapper JAR; restore it from the source repository.'
}
if ((Get-Sha256 $wrapperJar) -ne '498495120a03b9a6ab5d155f5de3c8f0d986a449153702fb80fc80e134484f17') {
    throw 'Unexpected Gradle wrapper JAR checksum.'
}

$jdkPath = Resolve-Jdk17 -RequestedJavaHome $JavaHome -SdkPath $sdkPath
$pythonPath = Resolve-Python311 -Requested $BuildPython

foreach ($directory in @(
        $cacheRoot,
        (Join-Path $cacheRoot "gradle-user-home"),
        (Join-Path $cacheRoot "android-user-home"),
        (Join-Path $cacheRoot "gradle-project-cache"),
        (Join-Path $cacheRoot "tmp"))) {
    New-Item -ItemType Directory -Path $directory -Force | Out-Null
}

# Stable local debug signing cache. The keystore never leaves the project .cache
# directory and is not used for release distribution.
$debugKeystore = Join-Path $cacheRoot "android-user-home/debug.keystore"
if (-not (Test-Path -LiteralPath $debugKeystore -PathType Leaf)) {
    $keytool = Join-Path $jdkPath "bin/keytool.exe"
    & $keytool "-genkeypair" "-keystore" $debugKeystore `
        "-storepass" "android" "-keypass" "android" `
        "-alias" "androiddebugkey" "-keyalg" "RSA" "-keysize" "2048" `
        "-validity" "10000" "-dname" "CN=Android Debug,O=Android,C=US"
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $debugKeystore -PathType Leaf)) {
        throw "Unable to create the local debug keystore at $debugKeystore."
    }
}

# Process-local only: no global environment changes, no SDK license acceptance, and no
# machine-wide trust or proxy modification. Gradle/Android caches stay on D:.
$env:JAVA_HOME = $jdkPath
$env:ANDROID_HOME = $sdkPath
$env:ANDROID_SDK_ROOT = $sdkPath
$env:GRADLE_USER_HOME = Join-Path $cacheRoot "gradle-user-home"
$env:ANDROID_USER_HOME = Join-Path $cacheRoot "android-user-home"
Remove-Item Env:ANDROID_PREFS_ROOT -ErrorAction SilentlyContinue
Remove-Item Env:ANDROID_SDK_HOME -ErrorAction SilentlyContinue
$env:TMP = Join-Path $cacheRoot "tmp"
$env:TEMP = $env:TMP
$env:Path = (Join-Path $jdkPath "bin") + [System.IO.Path]::PathSeparator + $env:Path

Write-Host "Using JDK: $jdkPath"
Write-Host "Using Python 3.11: $pythonPath"
Write-Host "Using Android SDK: $sdkPath"
Write-Host "Using Gradle user home: $env:GRADLE_USER_HOME"
Write-Host "Using Android user home: $env:ANDROID_USER_HOME"

Push-Location $androidRoot
try {
    & (Join-Path $androidRoot "gradlew.bat") `
        "-p" $androidRoot `
        "testDebugUnitTest" "assembleDebug" `
        "-PbuildPython=$pythonPath" `
        "--no-daemon" "--console=plain" `
        "--project-cache-dir" (Join-Path $cacheRoot "gradle-project-cache")
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
    $apkDestination = Join-Path $outputPath "nihaixia-local-debug.apk"
    Copy-Item -LiteralPath $apkPath -Destination $apkDestination -Force
    $apkPath = $apkDestination
}

$hash = Get-Sha256 $apkPath
Write-Host "APK: $apkPath"
Write-Host "APK SHA256: $hash"
