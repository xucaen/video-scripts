param (
    [string]$InputFile = "input.txt",
    [int]$FPS = 30,
    [int]$DesiredLengthInSeconds = 15,

    [int]$PixelsPerSecond = 50,
    [int]$HeaderPixelsPerSecond = 5,

    [int]$Width  = 1080,
    [int]$Height = 1920,

    [string]$Music = "",
    [string]$voice = "",

    [switch]$ShapeColorOscilate,
    [switch]$ShapeDropShadow,
    [switch]$Rotate,

    [string]$Theme = "default"
)
$env:FFREPORT = "file=ffmpeg_crash_log.txt:level=32"
$env:FONTCONFIG_FILE = "nul"
$env:FONTCONFIG_PATH = "nul"
$env:HOME = $PSScriptRoot
# Scaling Constants
[double]$BaseWidth  = 1080.00
[double]$BaseHeight = 1920.00
[double]$ScaleX = 1.0 * $Width / $BaseWidth
[double]$ScaleY = 1.0 * $Height / $BaseHeight
[double]$Scale = [Math]::Max(0.1, [Math]::Min($ScaleX, $ScaleY))


# External Scripts & Tools
$SignScript = Join-Path $PSScriptRoot "vsign.ps1"
$shapeScript = Join-Path $PSScriptRoot "pre-render_shapes.ps1"
$ffmpeg = "ffmpeg.exe"
$magick = "magick.exe"
$OutputDir = "."

. $SignScript

# Design Constants
$Design = @{
    HeaderY    = 150    # pixels from top for header
    BodyY      = 600    # pixels from top for body
    SpacerW    = 900    # keep this if using a bounding box or max width
    HeaderSize = 90     # font size for header
    BodySize   = 80     # font size for body
}

# Parallax Motion (Scaled)
[int]$PPS  = $PixelsPerSecond
[int]$HPPS = $HeaderPixelsPerSecond

# Theme Loading
function Get-Theme {
    param([string]$ThemeName)
    $localThemeFolder = Join-Path (Get-Location).Path "themes"
    $themePath = Join-Path $localThemeFolder "$ThemeName.ps1"
    if (!(Test-Path $themePath)) { throw "Theme not found: $ThemeName" }
    return & $themePath 
}



$ThemeData = Get-Theme $Theme
$FontPairs    = $ThemeData.FontPairs | Sort-Object { Get-Random }
$Colors       = $ThemeData.Colors | Sort-Object { Get-Random }
$ShapeColors  = $ThemeData.ShapeColors | Sort-Object { Get-Random }
$HeaderColors = $ThemeData.HeaderColors | Sort-Object { Get-Random }

# Music Setup
$MusicFiles = @()
$MusicIndex = 0
if (![string]::IsNullOrWhiteSpace($Music) -and (Test-Path $Music)) {
    $MusicFiles = Get-ChildItem -Path $Music -File | Where-Object { $_.Extension -match '\.(mp3|wav|m4a|aac|flac)$' } | Sort-Object { Get-Random }
}

$count = 0

###################################
# --- MAIN PROCESS ---
###################################

Get-Content $InputFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "") { continue }
    $count++

    # Selection Logic
    $idxFont   = ($count - 1) % $FontPairs.Count
    $idxColor  = ($count - 1) % $Colors.Count
    $idxHColor = ($count - 1) % $HeaderColors.Count
    $idxSCol   = ($count - 1) % $ShapeColors.Count

    # --- REVISED PATH ESCAPING ---
    $SelectedPair = $FontPairs[$idxFont]

    $headerFont = $SelectedPair.Header 
    $bodyFont   = $SelectedPair.Body   

    $headerColor  = $HeaderColors[$idxHColor]
    $bg           = $Colors[$idxColor]
    $scol         = $ShapeColors[$idxSCol]
    $FontColor    = $ThemeData.TextColors # Assuming single value or pick logic

    # --- STEP 1: RENDER BACKGROUND SHAPES ---
    Write-Host "Rendering shape background..." -ForegroundColor Cyan
    & $shapeScript `
        -FPS $FPS `
        -DesiredLengthInSeconds $DesiredLengthInSeconds `
        -Width $Width `
        -Height $Height `
        -ShapeDropShadow:$ShapeDropShadow `
        -Rotate:$Rotate `
        -Theme $Theme `
        -ShapeColor $scol `
        -BackgroundColor $bg

    if ($LASTEXITCODE -ne 0) {
        Write-Error "Background render failed with exit code $LASTEXITCODE"
        exit $LASTEXITCODE
    }

    $shapeVideo = "shape_.mp4"
    if (!(Test-Path $shapeVideo)) { 
        Write-Error "CRITICAL: $shapeVideo was not created by the shape script."
        exit 1 
    }

    # --- STEP 2: TEXT PARSING ---
    $headerText = ""
    $bodyText = $line
    if ($line -like "*:*") {
        $parts = $line -split ':', 2
        $headerText = ($parts[0].Trim() + ":")
        $bodyText   = $parts[1].Trim()
    }

    # --- STEP 3: PERSIST TEXT (Avoids escaping hell) ---


    # --- STEP 4: CALCULATE DIMENSIONS ---
    $headerFontSize = $Design.HeaderSize
    $bodyFontSize   = $Design.BodySize


# --- STEP 5: make the text frame ---
# Ensure fontsize uses the variables, not the (w-text_w) formula
Write-Host "DEBUG: HeaderSize: $headerFontSize, BodySize: $bodyFontSize, FontColor: $FontColor" -ForegroundColor Magenta
Write-Host "DEBUG: HeaderFont: $headerFont, BodyFont: $bodyFont" -ForegroundColor Magenta
$TextFrameFile = "temptext.png"


#########################################
### ImageMagick step ---
#########################################

$magickArgs = @(
    "-size", "${BaseWidth}x${BaseHeight}",
    "canvas:none",

    # --- Header ---
    "(",
        "-background", "none",
        "-fill", $headerColor,
        "-font", $headerFont,
        "-pointsize", $Design.HeaderSize,
        "-size", "$($BaseWidth - 100)x${BaseHeight}",
        "caption:$headerText",
    ")",
    "-gravity", "north",
    "-geometry", "+0+$($Design.HeaderY)",
    "-composite",

    # --- Body ---
    "(",
        "(", "-size", "${Design.SpacerW}x60", "canvas:none", ")",
        "(",
            "-background", "none",
            "-fill", $FontColor,
            "-font", $bodyFont,
            "-pointsize", $Design.BodySize,
            "-size", "$($BaseWidth - 100)x${BaseHeight}",
            "caption:$bodyText",
        ")",
        "-append",
    ")",
    "-gravity", "north",
    "-geometry", "+0+$($Design.BodyY)",
    "-composite", $TextFrameFile
)

# Execute
& $magick $magickArgs

if ($LASTEXITCODE -ne 0) {
    Write-Error "ImageMagick failed with exit code $LASTEXITCODE"
    exit $LASTEXITCODE
} else {
    Write-Host "Frame created: $TextFrameFile" -ForegroundColor Green
}

#######DEBUG CODE

Write-Host ""
Write-Host "DEBUG: filer is: $filter" -ForegroundColor Blue -BackgroundColor White
Write-Host ""

          # --- STEP 6: AUDIO ---
    $audioArgs = @()
    $hasAudio = $false
    if ($MusicFiles.Count -gt 0) {
        $CurrentMusic = $MusicFiles[$MusicIndex].FullName
        $audioArgs = @("-stream_loop", "-1", "-i", $CurrentMusic)
        $hasAudio = $true
        $MusicIndex = ($MusicIndex + 1) % $MusicFiles.Count
    }

    # --- STEP 7: FINAL RENDER ---
    $mp4Output = Join-Path $OutputDir ("img_{0:D3}.mp4" -f $count)

    $ffmpegArgs = @(
    "-y",
    "-i", $shapeVideo,   # background video
    "-i", $TextFrameFile   # rendered text frame
    )


    if ($hasAudio) { $ffmpegArgs += $audioArgs }

$ffmpegArgs += @(
    "-filter_complex", "[0:v][1:v]overlay=0:0[v]",
    "-map", "[v]",
    "-c:v", "libx264",
    "-pix_fmt", "yuv420p",
    "-t", $DesiredLengthInSeconds
)

    if ($hasAudio) {
        $ffmpegArgs += "-map", "2:a:0"
        $ffmpegArgs += "-shortest"
    }

    $ffmpegArgs += @("-movflags", "+faststart", "-g", ($FPS * 2), $mp4Output)

    Write-Host "Rendering final video: $mp4Output" -ForegroundColor Yellow
    & $ffmpeg $ffmpegArgs

    if (!(Test-Path $mp4Output)) {
        Write-Error "FFmpeg reported success, but $mp4Output is missing!"
        exit 1
    }
    # --- STEP 8: PUBLISH & CLEANUP ---
    if (Test-Path $mp4Output) {
        $NewFile = Publish-Video -FullName $mp4Output -Title "Video $count" -artist "James Barrett"
        
        if ($null -eq $NewFile -or !(Test-Path $NewFile)) {
                Write-Error "Publish-Video failed to return a valid path. Keeping original files for safety."
                exit 1
            }

            # Only cleanup if we reach this point safely
            Remove-Item $mp4Output, $shapeVideo, $TextFrameFile -ErrorAction SilentlyContinue
            Write-Host "Process for line $count complete.`n" -ForegroundColor Gray
    }
}