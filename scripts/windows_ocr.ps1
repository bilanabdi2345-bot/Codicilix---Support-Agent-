# Reads the text in screenshots and photos with Windows' own built-in text reader
# (Windows.Media.Ocr). Based on David's version (github.com/davidxu16/ai-assistant).
# It runs entirely on this computer: no internet, no account, and it saves nothing.
#
# Codicilix starts it with image paths as arguments. The argument "-" means: read one
# picture from the input pipe instead (sent as base64 text), so a pasted picture is
# never written to disk.
#
# It prints one line of JSON, in the same shape as the Mac reader (scripts/ocr.swift):
# [{"path", "text", "words": [{"t", "x", "y", "w", "h"}], "width", "height"}]
# Word boxes go from 0 to 1, measured from the top left of the picture.
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)

$ErrorActionPreference = 'Stop'
$out = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object System.Text.UTF8Encoding $false))
$out.AutoFlush = $true

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.InMemoryRandomAccessStream, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Storage.Streams.DataWriter, Windows.Storage.Streams, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]

# Windows' text reader is asynchronous; these wait for each step to finish.
$methods = [System.WindowsRuntimeSystemExtensions].GetMethods()
$asTask = $methods | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
$asTaskProgress = $methods | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperationWithProgress`2' } | Select-Object -First 1
function Wait-Op($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}
function Wait-OpProgress($op, [Type]$type, [Type]$progress) {
    $task = $asTaskProgress.MakeGenericMethod($type, $progress).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}

function Open-Stream($p) {
    if ($p -eq '-') {
        $bytes = [Convert]::FromBase64String([Console]::In.ReadToEnd().Trim())
        $mem = New-Object Windows.Storage.Streams.InMemoryRandomAccessStream
        $writer = New-Object Windows.Storage.Streams.DataWriter($mem.GetOutputStreamAt(0))
        $writer.WriteBytes($bytes)
        $null = Wait-Op ($writer.StoreAsync()) ([UInt32])
        $null = $writer.DetachStream()
        $mem.Seek(0)
        return $mem
    }
    $file = Wait-Op ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
    return Wait-Op ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
$results = @()
foreach ($p in $Paths) {
    if ($null -eq $engine) {
        $results += @{ path = $p; text = ''; words = @(); width = 0; height = 0; error = 'Windows has no text-recognition language installed' }
        continue
    }
    $stream = $null
    try {
        $stream = Open-Stream $p
        $decoder = Wait-Op ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Wait-Op ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Wait-Op ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        $W = [double]$bitmap.PixelWidth
        $H = [double]$bitmap.PixelHeight
        $lines = @()
        $words = @()
        foreach ($line in $result.Lines) {
            $lines += $line.Text
            foreach ($w in $line.Words) {
                $r = $w.BoundingRect
                $words += @{ t = $w.Text; x = $r.X / $W; y = $r.Y / $H; w = $r.Width / $W; h = $r.Height / $H }
            }
        }
        $results += @{ path = $p; text = ($lines -join "`n"); words = $words; width = $W; height = $H }
    } catch {
        $results += @{ path = $p; text = ''; words = @(); width = 0; height = 0; error = $_.Exception.Message }
    } finally {
        if ($stream) { $stream.Dispose() }
    }
}
$out.WriteLine((ConvertTo-Json -InputObject @($results) -Depth 5 -Compress))
