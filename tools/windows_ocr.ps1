# Reads the text in screenshots and photos with Windows' own built-in text reader
# (Windows.Media.Ocr). It runs entirely on this computer: no internet, no account,
# and it saves nothing. Second Brain starts it with the image paths as arguments,
# reads what it prints, and keeps the text in memory only for that one answer.
#
# Output: for each image, a line "<RS>path", then one line per line of text it read.
# A line "<RS>ERROR message" means that image couldn't be read. (<RS> is character 30.)
param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Paths)

$ErrorActionPreference = 'Stop'
$RS = [char]30
# Write UTF-8 straight to the output pipe (there's no console window to set an encoding on).
$out = New-Object System.IO.StreamWriter([Console]::OpenStandardOutput(), (New-Object System.Text.UTF8Encoding $false))
$out.AutoFlush = $true

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics, ContentType = WindowsRuntime]

# Windows' text reader is asynchronous; this waits for each step to finish.
$asTask = [System.WindowsRuntimeSystemExtensions].GetMethods() | Where-Object {
    $_.Name -eq 'AsTask' -and $_.GetParameters().Count -eq 1 -and
    $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | Select-Object -First 1
function Wait-Op($op, [Type]$type) {
    $task = $asTask.MakeGenericMethod($type).Invoke($null, @($op))
    $null = $task.Wait(-1)
    $task.Result
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
foreach ($p in $Paths) {
    $out.WriteLine("$RS$p")
    if ($null -eq $engine) {
        $out.WriteLine("${RS}ERROR Windows has no text-recognition language installed")
        continue
    }
    $stream = $null
    try {
        $file = Wait-Op ([Windows.Storage.StorageFile]::GetFileFromPathAsync($p)) ([Windows.Storage.StorageFile])
        $stream = Wait-Op ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Wait-Op ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Wait-Op ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Wait-Op ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])
        foreach ($line in $result.Lines) { $out.WriteLine($line.Text) }
    } catch {
        $out.WriteLine("${RS}ERROR $($_.Exception.Message)")
    } finally {
        if ($stream) { $stream.Dispose() }
    }
}
