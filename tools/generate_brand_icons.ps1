Add-Type -AssemblyName System.Drawing

function New-BrandIcon([int]$size, [string]$path) {
  $scale = 4
  $bmp = New-Object System.Drawing.Bitmap ($size * $scale), ($size * $scale), ([System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
  $g.Clear([System.Drawing.Color]::Transparent)
  $r = New-Object System.Drawing.RectangleF (2*$scale), (2*$scale), (124*$scale), (124*$scale)
  $bg = New-Object System.Drawing.Drawing2D.LinearGradientBrush $r, ([System.Drawing.Color]::FromArgb(255,18,59,120)), ([System.Drawing.Color]::FromArgb(255,4,19,38)), 45
  $g.FillPath($bg, (New-RoundedPath $r (28*$scale)))
  $pen = New-Object System.Drawing.Pen ([System.Drawing.Color]::FromArgb(255,23,98,170)), (2*$scale)
  $g.DrawPath($pen, (New-RoundedPath $r (28*$scale)))
  $white = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::White)
  $g.FillPolygon($white, [System.Drawing.Point[]]@((New-Object System.Drawing.Point (24*$scale),(92*$scale)),(New-Object System.Drawing.Point (48*$scale),(68*$scale)),(New-Object System.Drawing.Point (48*$scale),(88*$scale)),(New-Object System.Drawing.Point (30*$scale),(106*$scale)),(New-Object System.Drawing.Point (30*$scale),(92*$scale))))
  $g.FillPolygon($white, [System.Drawing.Point[]]@((New-Object System.Drawing.Point (31*$scale),(46*$scale)),(New-Object System.Drawing.Point (46*$scale),(56*$scale)),(New-Object System.Drawing.Point (46*$scale),(70*$scale)),(New-Object System.Drawing.Point (31*$scale),(60*$scale))))
  $g.FillRectangle($white, (44*$scale),(59*$scale),(17*$scale),(26*$scale))
  $g.FillRectangle($white, (61*$scale),(59*$scale),(18*$scale),(17*$scale))
  $g.FillRectangle($white, (85*$scale),(50*$scale),(17*$scale),(45*$scale))
  $redRect = New-Object System.Drawing.Rectangle (74*$scale),(22*$scale),(20*$scale),(57*$scale)
  $red = New-Object System.Drawing.Drawing2D.LinearGradientBrush -ArgumentList $redRect, ([System.Drawing.Color]::FromArgb(255,255,121,92)), ([System.Drawing.Color]::FromArgb(255,255,0,53)), 45
  $g.FillRectangle($red,(74*$scale),(40*$scale),(20*$scale),(39*$scale)); $g.FillRectangle($red,(84*$scale),(22*$scale),(10*$scale),(18*$scale)); $g.FillRectangle($red,(78*$scale),(79*$scale),(6*$scale),(25*$scale))
  $blue = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255,138,178,237)); $pink = New-Object System.Drawing.SolidBrush ([System.Drawing.Color]::FromArgb(255,255,41,71))
  $g.FillRectangle($blue,17*$scale,34*$scale,7*$scale,7*$scale); $g.FillRectangle($blue,18*$scale,78*$scale,7*$scale,7*$scale); $g.FillRectangle($blue,26*$scale,87*$scale,7*$scale,7*$scale)
  $g.FillRectangle($pink,28*$scale,27*$scale,9*$scale,9*$scale); $g.FillRectangle($pink,21*$scale,45*$scale,7*$scale,7*$scale)
  $out = New-Object System.Drawing.Bitmap $size,$size; $og=[System.Drawing.Graphics]::FromImage($out); $og.InterpolationMode=[System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic; $og.DrawImage($bmp,0,0,$size,$size); $out.Save($path,[System.Drawing.Imaging.ImageFormat]::Png); $og.Dispose(); $out.Dispose(); $g.Dispose(); $bmp.Dispose()
}
function New-RoundedPath($rect, [float]$radius) { $p=New-Object System.Drawing.Drawing2D.GraphicsPath; $d=$radius*2; $p.AddArc($rect.X,$rect.Y,$d,$d,180,90); $p.AddArc($rect.Right-$d,$rect.Y,$d,$d,270,90); $p.AddArc($rect.Right-$d,$rect.Bottom-$d,$d,$d,0,90); $p.AddArc($rect.X,$rect.Bottom-$d,$d,$d,90,90); $p.CloseFigure(); return $p }
$root = Split-Path -Parent $PSScriptRoot
foreach ($s in 16,48,128) { New-BrandIcon $s (Join-Path $root "chrome-extension/assets/icon$s.png") }
