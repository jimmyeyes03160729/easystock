# Generates the Chrome 2.0 toolbar icons: a monochrome rounded square with a white 「沖」 glyph.
# Low-key black/white, no red or gradients, legible at 16 px on light and dark toolbars.
# Requires Windows (GDI+) with the Microsoft JhengHei font. Output: assets/icon16.png, icon48.png, icon128.png.
param([string]$OutDir = (Join-Path $PSScriptRoot '..\assets'))
Add-Type -AssemblyName System.Drawing

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

# Per size: square inset (Chrome Web Store guidance: 128 px icon uses ~96 px artwork), corner radius, glyph size.
$specs = @(
  @{ size = 16;  inset = 0;  radius = 3;  font = 13.5; dy = 0.2 },
  @{ size = 48;  inset = 2;  radius = 9;  font = 34;   dy = 0.5 },
  @{ size = 128; inset = 16; radius = 18; font = 70;   dy = 1 }
)
$fontFamily = 'Microsoft JhengHei'
foreach ($s in $specs) {
  $n = $s.size
  $bmp = New-Object System.Drawing.Bitmap($n, $n, [System.Drawing.Imaging.PixelFormat]::Format32bppArgb)
  $g = [System.Drawing.Graphics]::FromImage($bmp)
  $g.Clear([System.Drawing.Color]::Transparent)
  $g.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
  $g.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
  $g.PixelOffsetMode = [System.Drawing.Drawing2D.PixelOffsetMode]::HighQuality
  $side = $n - 2 * $s.inset
  $path = New-RoundedPath $s.inset $s.inset $side $side $s.radius
  $bg = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 24, 24, 27))   # zinc-900
  $g.FillPath($bg, $path)
  if ($n -ge 48) {
    $pen = New-Object System.Drawing.Pen([System.Drawing.Color]::FromArgb(255, 82, 82, 91), [float]([Math]::Max(1, $n / 64)))  # zinc-600 hairline for dark toolbars
    $g.DrawPath($pen, $path)
  }
  $font = New-Object System.Drawing.Font($fontFamily, [float]$s.font, [System.Drawing.FontStyle]::Bold, [System.Drawing.GraphicsUnit]::Pixel)
  $fmt = New-Object System.Drawing.StringFormat
  $fmt.Alignment = [System.Drawing.StringAlignment]::Center
  $fmt.LineAlignment = [System.Drawing.StringAlignment]::Center
  $fg = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(255, 250, 250, 250))
  $rect = New-Object System.Drawing.RectangleF([float]0, [float]$s.dy, [float]$n, [float]$n)
  $g.DrawString([string][char]0x6C96, $font, $fg, $rect, $fmt)
  $g.Dispose()
  $out = Join-Path $OutDir ("icon{0}.png" -f $n)
  $bmp.Save($out, [System.Drawing.Imaging.ImageFormat]::Png)
  $bmp.Dispose()
  Write-Output ("wrote {0}" -f $out)
}
