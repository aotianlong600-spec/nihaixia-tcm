param(
    [Parameter(Mandatory = $true)][string]$ImageDir,
    [Parameter(Mandatory = $true)][string]$OutJson,
    [string]$LangTag = "zh-Hans-CN"
)

Add-Type -AssemblyName System.Runtime.WindowsRuntime

$asTaskGeneric = ([System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1'
})[0]

function Await-WinRT($WinRtTask, $ResultType) {
    $asTask = $asTaskGeneric.MakeGenericMethod($ResultType)
    $netTask = $asTask.Invoke($null, @($WinRtTask))
    $netTask.Wait(-1) | Out-Null
    return $netTask.Result
}

[Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime] | Out-Null
[Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime] | Out-Null
[Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime] | Out-Null

$lang = New-Object Windows.Globalization.Language($LangTag)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
if (-not $engine) {
    throw "Failed to create OcrEngine for language tag: $LangTag"
}

$files = Get-ChildItem -Path $ImageDir -Filter "*.png" | Sort-Object Name
$results = [System.Collections.Generic.List[object]]::new()
$sw = [System.Diagnostics.Stopwatch]::StartNew()

foreach ($f in $files) {
    $fileObj = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($f.FullName)) ([Windows.Storage.StorageFile])
    $stream = Await-WinRT ($fileObj.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
    $decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
    $bitmap = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
    $ocrRes = Await-WinRT ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

    $lines = [System.Collections.Generic.List[object]]::new()
    foreach ($ln in $ocrRes.Lines) {
        $words = $ln.Words
        if ($words.Count -gt 0) {
            $minX = [double]::MaxValue
            $minY = [double]::MaxValue
            $maxX = [double]::MinValue
            $maxY = [double]::MinValue
            foreach ($w in $words) {
                $r = $w.BoundingRect
                if ($r.X -lt $minX) { $minX = $r.X }
                if ($r.Y -lt $minY) { $minY = $r.Y }
                if (($r.X + $r.Width) -gt $maxX) { $maxX = $r.X + $r.Width }
                if (($r.Y + $r.Height) -gt $maxY) { $maxY = $r.Y + $r.Height }
            }
            $lines.Add(@{
                text = $ln.Text
                x = [Math]::Round($minX, 1)
                y = [Math]::Round($minY, 1)
                x2 = [Math]::Round($maxX, 1)
                y2 = [Math]::Round($maxY, 1)
            })
        }
    }
    $results.Add(@{
        file = $f.Name
        width = $bitmap.PixelWidth
        height = $bitmap.PixelHeight
        lines = $lines
    })
    $bitmap.Dispose()
    $stream.Dispose()
}

$sw.Stop()
Write-Output ("WinRT OCR ({0}): pages={1}, elapsed_ms={2}" -f $LangTag, $results.Count, $sw.ElapsedMilliseconds)
[System.IO.File]::WriteAllText($OutJson, ($results | ConvertTo-Json -Depth 6 -Compress), (New-Object System.Text.UTF8Encoding($false)))
