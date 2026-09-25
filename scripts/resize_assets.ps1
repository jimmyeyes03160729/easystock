Add-Type -AssemblyName System.Drawing

$assetsDir = "c:\Users\Jimmy\Projects\easystock\chrome-store-assets"

function Convert-Image {
    param(
        [string]$inputFile,
        [string]$outputFile,
        [int]$targetWidth,
        [int]$targetHeight
    )

    Write-Host "Processing $inputFile -> $outputFile ($targetWidth x $targetHeight)..."
    $inImg = [System.Drawing.Image]::FromFile($inputFile)
    
    # 建立 24 位元 RGB 點陣圖 (無 Alpha 透明通道，符合 Chrome Web Store 規範)
    $outBmp = New-Object System.Drawing.Bitmap($targetWidth, $targetHeight, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $gfx = [System.Drawing.Graphics]::FromImage($outBmp)
    
    # 設定最高品質算繪
    $gfx.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
    $gfx.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::HighQuality
    $gfx.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
    $gfx.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
    
    # 底色填充深色背景以防任何留白
    $brush = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(11, 15, 25))
    $gfx.FillRectangle($brush, 0, 0, $targetWidth, $targetHeight)
    
    # 將原始圖片縮放繪製至目標畫布
    $gfx.DrawImage($inImg, 0, 0, $targetWidth, $targetHeight)
    
    # 儲存為 24 位元 PNG 與高品質 JPEG
    $outPng = $outputFile
    $outJpg = [System.IO.Path]::ChangeExtension($outputFile, ".jpg")
    
    $outBmp.Save($outPng, [System.Drawing.Imaging.ImageFormat]::Png)
    $outBmp.Save($outJpg, [System.Drawing.Imaging.ImageFormat]::Jpeg)
    
    $gfx.Dispose()
    $outBmp.Dispose()
    $inImg.Dispose()
    
    Write-Host "Created: $outPng and $outJpg"
}

# 1. 跑馬燈大宣傳圖塊 (1400x560)
Convert-Image -inputFile "$assetsDir\marquee_raw.png" -outputFile "$assetsDir\marquee_promo_1400x560.png" -targetWidth 1400 -targetHeight 560

# 2. 小型宣傳圖塊 (440x280)
Convert-Image -inputFile "$assetsDir\small_raw.png" -outputFile "$assetsDir\small_promo_440x280.png" -targetWidth 440 -targetHeight 280

# 3. 螢幕展示截圖 (1280x800)
Convert-Image -inputFile "$assetsDir\screen_raw.png" -outputFile "$assetsDir\screenshot_1280x800.png" -targetWidth 1280 -targetHeight 800

Write-Host "All promotional assets generated successfully!"
