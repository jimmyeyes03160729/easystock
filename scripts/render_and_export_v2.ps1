Add-Type -AssemblyName System.Drawing

$edgePath = "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
if (-not (Test-Path $edgePath)) {
    $edgePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"
}

function Render-HtmlToPng {
    param(
        [string]$HtmlFile,
        [string]$OutPng,
        [int]$Width,
        [int]$Height
    )

    $fullHtml = (Resolve-Path $HtmlFile).ProviderPath
    $fullOut = [System.IO.Path]::GetFullPath($OutPng)

    $args = @(
        "--headless",
        "--disable-gpu",
        "--hide-scrollbars",
        "--force-device-scale-factor=1",
        "--window-size=$Width,$Height",
        "--virtual-time-budget=4500",
        "--screenshot=$fullOut",
        "file:///$($fullHtml.Replace('\', '/'))"
    )

    Write-Output "Rendering $HtmlFile to $OutPng ($Width x $Height)..."
    $proc = Start-Process -FilePath $edgePath -ArgumentList $args -Wait -PassThru -NoNewWindow
    if ($proc.ExitCode -ne 0) {
        Write-Warning "Process exited with code $($proc.ExitCode)"
    }
}

function Convert-ToFinalFormats {
    param(
        [string]$SourcePng,
        [string]$BaseName,
        [int]$Width,
        [int]$Height
    )

    $srcPath = [System.IO.Path]::GetFullPath($SourcePng)
    $srcImg = [System.Drawing.Image]::FromFile($srcPath)

    # 1. Create true 24-bit RGB bitmap (No Alpha channel)
    $targetBmp = New-Object System.Drawing.Bitmap($Width, $Height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $graphics = [System.Drawing.Graphics]::FromImage($targetBmp)
    $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

    $rect = New-Object System.Drawing.Rectangle(0, 0, $Width, $Height)
    $graphics.DrawImage($srcImg, $rect, 0, 0, $srcImg.Width, $srcImg.Height, [System.Drawing.GraphicsUnit]::Pixel)

    $graphics.Dispose()
    $srcImg.Dispose()

    # Save as 24-bit PNG
    $pngPath = Join-Path "chrome-store-assets" ($BaseName + ".png")
    $targetBmp.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)

    # Save as High-Quality JPEG (Quality 96)
    $jpgPath = Join-Path "chrome-store-assets" ($BaseName + ".jpg")
    $jpegCodec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.FormatID -eq [System.Drawing.Imaging.ImageFormat]::Jpeg.Guid }
    $encoderParams = New-Object System.Drawing.Imaging.EncoderParameters(1)
    $encoderParams.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]96)
    $targetBmp.Save($jpgPath, $jpegCodec, $encoderParams)

    $targetBmp.Dispose()

    Write-Output "Generated final assets: $pngPath and $jpgPath ($Width x $Height)"
}

Write-Output "=== Starting V2 Store Assets Generation ==="

# 1. Small Promo Tile (440x280)
Render-HtmlToPng "chrome-store-assets\small_v2_clean.html" "chrome-store-assets\raw_small_v2.png" 440 280
Convert-ToFinalFormats "chrome-store-assets\raw_small_v2.png" "small_promo_440x280" 440 280

# 2. Store Screenshot (1280x800)
Render-HtmlToPng "chrome-store-assets\screen_v2_clean.html" "chrome-store-assets\raw_screen_v2.png" 1280 800
Convert-ToFinalFormats "chrome-store-assets\raw_screen_v2.png" "screenshot_1280x800" 1280 800

# 3. Marquee Promo Tile (1400x560)
Render-HtmlToPng "chrome-store-assets\marquee_v2_clean.html" "chrome-store-assets\raw_marquee_v2.png" 1400 560
Convert-ToFinalFormats "chrome-store-assets\raw_marquee_v2.png" "marquee_promo_1400x560" 1400 560

Write-Output "=== V2 Store Assets Generation Complete! ==="
