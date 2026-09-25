Add-Type -AssemblyName System.Drawing

function Save-StoreAsset {
    param(
        [string]$SourcePath,
        [string]$TargetBaseName,
        [int]$TargetWidth,
        [int]$TargetHeight
    )

    $srcPath = (Resolve-Path $SourcePath).ProviderPath
    $srcImg = [System.Drawing.Image]::FromFile($srcPath)

    # 1. Create true 24-bit RGB bitmap (No Alpha channel)
    $targetBmp = New-Object System.Drawing.Bitmap($TargetWidth, $TargetHeight, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $graphics = [System.Drawing.Graphics]::FromImage($targetBmp)
    $graphics.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $graphics.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality

    $rect = New-Object System.Drawing.Rectangle(0, 0, $TargetWidth, $TargetHeight)
    $graphics.DrawImage($srcImg, $rect, 0, 0, $srcImg.Width, $srcImg.Height, [System.Drawing.GraphicsUnit]::Pixel)

    $graphics.Dispose()
    $srcImg.Dispose()

    # Save as 24-bit PNG
    $pngPath = Join-Path "chrome-store-assets" ($TargetBaseName + ".png")
    $targetBmp.Save($pngPath, [System.Drawing.Imaging.ImageFormat]::Png)

    # Save as JPEG (Quality 96)
    $jpgPath = Join-Path "chrome-store-assets" ($TargetBaseName + ".jpg")
    $jpegCodec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.FormatID -eq [System.Drawing.Imaging.ImageFormat]::Jpeg.Guid }
    $encoderParams = New-Object System.Drawing.Imaging.EncoderParameters(1)
    $encoderParams.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter([System.Drawing.Imaging.Encoder]::Quality, [long]96)
    $targetBmp.Save($jpgPath, $jpegCodec, $encoderParams)

    $targetBmp.Dispose()

    Write-Output ("Saved: " + $pngPath + " & " + $jpgPath + " (" + $TargetWidth + "x" + $TargetHeight + ")")
}

Write-Output "=== Exporting Store Assets in 24-bit PNG & High-Quality JPG ==="

# 1. Marquee Promo (1400x560)
Save-StoreAsset "chrome-store-assets\render_marquee.png" "marquee_promo_1400x560" 1400 560

# 2. Small Promo (440x280)
Save-StoreAsset "chrome-store-assets\render_small.png" "small_promo_440x280" 440 280

# 3. Store Screenshot (1280x800)
Save-StoreAsset "chrome-store-assets\render_screen.png" "screenshot_1280x800" 1280 800
