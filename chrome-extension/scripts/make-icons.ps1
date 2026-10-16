# Generates the Chrome toolbar icons from the official EasyStock logo (repo: icon/LOGO.png, the same
# mark used on jimmyeyes.com/easystock). The 「沖」 glyph is cropped tightly so it fills the icon
# (large and legible at 16 px), then a rounded-tile mask is applied. Output: assets/icon16/48/128.png.
# Requires Windows (GDI+).
param(
  [string]$Source = (Join-Path $PSScriptRoot '..\..\icon\LOGO.png'),
  [string]$OutDir = (Join-Path $PSScriptRoot '..\assets')
)
Add-Type -AssemblyName System.Drawing

# Glyph bounds measured on the 1254 px source: x 234–1002, y 208–1016 (centre ≈ 618, 612).
# An 880 px square around the centre keeps the whole glyph with a thin margin of the navy tile.
$crop = New-Object System.Drawing.Rectangle(178, 172, 880, 880)
$src = [System.Drawing.Bitmap]::FromFile((Resolve-Path $Source))

function New-RoundedPath([float]$x, [float]$y, [float]$w, [float]$h, [float]$r) {
  $p = New-Object System.Drawing.Drawing2D.GraphicsPath
  $d = $r * 2
  $p.AddArc($x, $y, $d, $d, 180, 90)
  $p.AddArc($x + $w - $d, $y, $d, $d, 270, 90)
  $p.AddArc($x + $w - $d, $y + $h - $d, $d, $d, 0, 90)
  $p.AddArc($x, $y + $h - $d, $d, $d, 90, 90)
  $p.CloseFigure()
  return $p
}

foreach ($n in 16, 48, 128) {
  $bmp = New-Object System.Drawing.Bitmap($n, $n, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::Transparent)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  $g.CompositingQuality = [System.Drawing.Drawing2D.CompositingQuality]::HighQuality
  $radius = [Math]::Max(2, [Math]::Round($n * 0.18))
  $path = New-RoundedPath 0 0 $n $n $radius
  $g.SetClip($path)
  $attrs = New-Object System.Drawing.Imaging.ImageAttributes
  $attrs.SetWrapMode([System.Drawing.Drawing2D.WrapMode]::TileFlipXY)  # no dark fringe at the crop edge
  $g.DrawImage($src, (New-Object System.Drawing.Rectangle(0, 0, $n, $n)), $crop.X, $crop.Y, $crop.Width, $crop.Height, [System.Drawing.GraphicsUnit]::Pixel, $attrs)
  $g.Dispose()
  $out = Join-Path $OutDir ("icon{0}.png" -f $n)
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Output ("wrote {0}" -f $out)
}
$src.Dispose()
