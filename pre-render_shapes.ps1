param (
    [int]$FPS = 30,
    [int]$DesiredLengthInSeconds = 15,
    [int]$Width  = 1080,
    [int]$Height = 1920,
    [switch]$ShapeDropShadow,
    [switch]$Rotate,
    [string]$Theme = "default",
    [string]$ShapeColor = "#FFFFFF",
    [string]$BackgroundColor = "#000000"
)

$env:MAGICK_MEMORY_LIMIT='16GiB'
$env:MAGICK_MAP_LIMIT='16GiB'
$env:MAGICK_DISK_LIMIT='160GiB'
$env:MAGICK_THREAD_LIMIT = 8

$magick = "magick.exe"
$ffmpeg = "ffmpeg.exe"
$OutputDir = "."

function Get-Theme {
    param([string]$ThemeName)
    $themePath = Join-Path (Join-Path (Get-Location).Path "themes") "${ThemeName}.ps1"
    if (!(Test-Path $themePath)) { throw "Theme not found: $ThemeName" }
    return & $themePath
}

function Get-ContrastColor {
    param([string]$hexColor)
    $cleanHex = $hexColor.Replace("#", "")
  if ($cleanHex.Length -eq 3) {
        $r = $cleanHex[0]; $g = $cleanHex[1]; $b = $cleanHex[2]
        $cleanHex = "$r$r$g$g$b$b"
    }
    if ($cleanHex.Length -ne 6) { return "rgba(0,0,0,1)" }

    $R = [Convert]::ToInt32($cleanHex.Substring(0, 2), 16)
    $G = [Convert]::ToInt32($cleanHex.Substring(2, 2), 16)
    $B = [Convert]::ToInt32($cleanHex.Substring(4, 2), 16)

    $Brightness = ($R * 0.299) + ($G * 0.587) + ($B * 0.114)
    if ($Brightness -lt 128) { return "white" }
    return "black"
}

$ThemeData = Get-Theme $Theme
$Shapes = $ThemeData.Shapes
$Quadrants = @("northwest", "northeast", "southwest", "southeast")
$startQuad = $Quadrants | Get-Random
$shape = $Shapes | Get-Random
$bg = $BackgroundColor
$scol = $ShapeColor


    $ShadowColor = Get-ContrastColor $bg

    # ---------- PRE-RENDER ASSETS (ONCE) ----------

    $shapePng  = "shape_$([guid]::NewGuid()).png"
    $shadowPng = "shadow_$([guid]::NewGuid()).png"

    # Setup movement coordinates
    switch ($startQuad) {
        "northwest" { $endQuad = "southeast"; $sx = $Width/4;  $sy = $Height/4;  $ex = 3*$Width/4; $ey = 3*$Height/4 }
        "northeast" { $endQuad = "southwest"; $sx = 3*$Width/4; $sy = $Height/4;  $ex = $Width/4;  $ey = 3*$Height/4 }
        "southwest" { $endQuad = "northeast"; $sx = $Width/4;  $sy = 3*$Height/4; $ex = 3*$Width/4; $ey = $Height/4 }
        "southeast" { $endQuad = "northwest"; $sx = 3*$Width/4; $sy = 3*$Height/4; $ex = $Width/4;  $ey = $Height/4 }
    }

    $shapeLayerW = [int]($Width)
    $shapeLayerH = [int]($Height)

    $offsetX = ($shapeLayerW / 2) 
    $offsetY = ($shapeLayerH / 2) 

    # --- measure shape bounds ---
    $tempMeasure = "measure_$([guid]::NewGuid()).png"

    & $magick `
        -size 2000x2000 xc:none `
        -fill white `
        -draw "$shape" `
        -trim `
        -format "%w %h" info: > $tempMeasure

    $measure = Get-Content $tempMeasure
    Remove-Item $tempMeasure -ErrorAction SilentlyContinue

    $parts = $measure -split " "
    $shapeW = [double]$parts[0]
    $shapeH = [double]$parts[1]

    # --- compute proper scale ---
    $targetSize = [Math]::Min($Width, $Height) * 0.4

    $scaleX = $targetSize / $shapeW
    $scaleY = $targetSize / $shapeH
    $scale = [Math]::Min($scaleX, $scaleY)
    $scaleShadow = $scale*1.1

    # render shape with dynamic scale
    & $magick `
        -size 2000x2000 xc:none `
        -fill $scol `
        -gravity center `
        -draw "scale $scale,$scale translate $offsetX,$offsetY $shape" `
        $shapePng

    # shadow
    if ($ShapeDropShadow) {
        & $magick `
            -size 2000x2000 xc:none `
            -fill $ShadowColor `
            -gravity center `
            -draw "scale $scaleShadow,$scaleShadow translate $offsetX+10,$offsetY+10 $shape" `
            $shadowPng
    }

    

    $inputs = @()
    $filter = ""

    # background color source
    $inputs += "-f"
    $inputs += "lavfi"
    $inputs += "-i"
    $inputs += "color=c=${bg}:s=${Width}x${Height}:d=$DesiredLengthInSeconds"

    $inputIndex = 1
    $baseRef = "0:v" # Start with the background

            # shadow layer
    if ($ShapeDropShadow) {
        $inputs += "-loop"
        $inputs += "1"
        $inputs += "-i"
        $inputs += $shadowPng

        $rot = if ($Rotate) { "rotate=angle='t*0.5':c=none," } else { "" }

        $filter += "[${inputIndex}:v]format=rgba,${rot} fade=t=in:st=0:d=2:alpha=1[shadow];"

        $filter += "[$baseRef][shadow]overlay=x='${sx}+(${ex}-${sx})*(t/${DesiredLengthInSeconds})-w/2':y='${sy}+(${ey}-${sy})*(t/${DesiredLengthInSeconds})-h/2':shortest=1[tmp_shadow];"

        $baseRef = "tmp_shadow"
        $inputIndex++
    }

    # shape layer
    $inputs += "-loop"
    $inputs += "1"
    $inputs += "-i"
    $inputs += $shapePng

    $rot = if ($Rotate) { "rotate=angle='t*0.5':c=none," } else { "" }

    $filter += "[${inputIndex}:v]format=rgba,${rot} fade=t=in:st=0:d=2:alpha=1[shape];"
    $filter += "[$baseRef][shape]overlay=x='${sx}+(${ex}-${sx})*(t/${DesiredLengthInSeconds})-w/2':y='${sy}+(${ey}-${sy})*(t/${DesiredLengthInSeconds})-h/2':shortest=1[outv]"

    # ---------- OUTPUT ----------

    $bgHex = $bg.Replace("#","")
    $scHex = $scol.Replace("#","")
    $mp4Output = Join-Path $OutputDir "shape_.mp4"

    & $ffmpeg `
        -y `
        $inputs `
        -filter_complex $filter `
        -shortest `
        -map "[outv]" `
        -r $FPS `
        -c:v libx264 `
        -preset veryfast `
        -crf 24 `
        -pix_fmt yuv420p `
        $mp4Output

    # cleanup
    Remove-Item $shapePng -ErrorAction SilentlyContinue
    if ($ShapeDropShadow) { Remove-Item $shadowPng -ErrorAction SilentlyContinue }

