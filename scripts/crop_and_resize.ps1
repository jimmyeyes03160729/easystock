Add-Type -AssemblyName System.Drawing

function Get-CardBounds {
    param([string]$FilePath)
    $path = (Resolve-Path $FilePath).ProviderPath
    $bmp = [System.Drawing.Bitmap]::FromFile($path)
    $bgColor = $bmp.GetPixel(5, 5)
    
    $w = $bmp.Width
    $h = $bmp.Height
    $minX = $w; $maxX = 0; $minY = $h; $maxY = 0

    # Sample pixels to locate foreground
    for ($y = 0; $y -lt $h; $y += 4) {
        for ($x = 0; $x -lt $w; $x += 4) {
            $c = $bmp.GetPixel($x, $y)
            $diff = [Math]::Abs([int]$c.R - [int]$bgColor.R) + [Math]::Abs([int]$c.G - [int]$bgColor.G) + [Math]::Abs([int]$c.B - [int]$bgColor.B)
            if ($diff -gt 35) {
                if ($x -lt $minX) { $minX = $x }
                if ($x -gt $maxX) { $maxX = $x }
                if ($y -lt $minY) { $minY = $y }
                if ($y -gt $maxY) { $maxY = $y }
            }
        }
    }
    $bmp.Dispose()
    return @{
        MinX = $minX
        MaxX = $maxX
        MinY = $minY
        MaxY = $maxY
        Width = ($maxX - $minX)
        Height = ($maxY - $minY)
    }
}

Write-Output "=== Analyzing Image Bounds ==="
$small = Get-CardBounds "chrome-store-assets\small_hd.png"
Write-Output ("Small HD: " + ($small | ConvertTo-Json -Compress))

$marquee = Get-CardBounds "chrome-store-assets\marquee_hd.png"
Write-Output ("Marquee HD: " + ($marquee | ConvertTo-Json -Compress))

$screen = Get-CardBounds "chrome-store-assets\screen_hd.png"
Write-Output ("Screen HD: " + ($screen | ConvertTo-Json -Compress))
