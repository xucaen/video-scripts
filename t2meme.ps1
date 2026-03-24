param (
    [string]$InputFile = "input.txt",
    [int]$FPS = 30,
    [int]$DesiredLengthInSeconds = 15,

    [int]$PixelsPerSecond = 50,
    [int]$HeaderPixelsPerSecond = 5,

    # Target Output Resolution (final rendered video size)
    [int]$Width  = 1080,
    [int]$Height = 1920,

    #audio files
    [string]$Music = "",
    [string]$voice = "",

    [switch]$ShapeColorOscilate,
    [switch]$ShapeDropShadow,

    ##New and improved with Themes! ;-)
   # [ValidateSet("TruthDrops", "BakedWisdom")]
    [string]$Theme = "default"

)

$SignScript = Join-Path $PSScriptRoot "vsign.ps1"
. $SignScript
if (-not (Get-Command Publish-Video -ErrorAction SilentlyContinue)) {
    Write-Error "The file $SignScript loaded, but it doesn't contain the 'Publish-Video' function!"
    exit
}
# Limit ImageMagick threading for stability/performance balance
$env:MAGICK_THREAD_LIMIT = 8


###################################
# --- Scaling System ---
# Keeps layout proportional across resolutions
###################################
    # Base Design Reference (the canvas size everything was originally designed for)
[double]$BaseWidth  = 1080.00
[double]$BaseHeight = 1920.00

[double]$ScaleX = 1.0 * $Width / $BaseWidth
[double]$ScaleY = 1.0 * $Height / $BaseHeight

# unified scale (prevents distortion by locking aspect consistency)
[double]$Scale = [Math]::Max(0.1, [Math]::Min($ScaleX, $ScaleY))

# helper for scaling values consistently across X/Y axes or uniform scale
function Scale([double]$value, [switch]$X, [switch]$Y) {
    if ($X) { return [int]($value * $ScaleX) }
    if ($Y) { return [int]($value * $ScaleY) }
    return [int]($value * $Scale)
}

###################################
# --- Text Safety (ImageMagick escaping) ---
###################################

function Protect-MagickText {
    param([string]$RawText)

    if ([string]::IsNullOrWhiteSpace($RawText)) { return "" }

    # Escape backslashes (critical for ImageMagick parsing safety)
    $Clean = $RawText.Replace('\', '\\')

    # Escape percent signs (ImageMagick caption parser uses % internally)
    $Clean = $Clean.Replace('%', '%%')

    # Escape single quotes for PowerShell/ImageMagick interaction
    $Clean = $Clean.Replace("'", "\'")

    # Prevent @ symbol from being treated as file input
    if ($Clean.StartsWith("@")) {
        $Clean = " " + $Clean
    }

    return $Clean
}


#####################################
##   Themes!
#####################################

function Get-Theme {
    param([string]$ThemeName)

    $localThemeFolder = Join-Path (Get-Location).Path "themes"
    $themePath = Join-Path $localThemeFolder "$ThemeName.ps1"

    if (!(Test-Path $themePath)) {
        throw "Theme not found: $ThemeName"
    }

    $themeData = & $themePath   # execute script, capture returned hashtable

    $required = @("FontPairs", "Colors", "ShapeColors", "HeaderColors", "Shapes")

    foreach ($key in $required) {
        if (-not $themeData.ContainsKey($key)) {
            throw "Theme missing required field: $key"
        }
    }

    return $themeData
}

function Get-ContrastColor {
    param([string]$hexColor)

    # Remove the # if present
    $cleanHex = $hexColor.Replace("#", "")

    # If it's a shorthand hex (e.g., F00), expand it (e.g., FF0000)
    if ($cleanHex.Length -eq 3) {
        $cleanHex = "$($cleanHex[0])$($cleanHex[0])$($cleanHex[1])$($cleanHex[1])$($cleanHex[2])$($cleanHex[2])"
    }

    # If it's not a valid 6-digit hex now, default to dark shadow
    if ($cleanHex.Length -ne 6) { return "rgba(0,0,0,0.4)" }

    # Convert Hex parts to Integers
    $R = [Convert]::ToInt32($cleanHex.Substring(0, 2), 16)
    $G = [Convert]::ToInt32($cleanHex.Substring(2, 2), 16)
    $B = [Convert]::ToInt32($cleanHex.Substring(4, 2), 16)

    # Calculate Perceived Brightness (0 to 255)
    $Brightness = ($R * 0.299) + ($G * 0.587) + ($B * 0.114)

    # If Brightness < 128, it's a dark background -> Use Light Shadow
    if ($Brightness -lt 128) {
        return "rgba(255,255,255,1)" 
    } 
    
    # Otherwise, it's a light background -> Use Dark Shadow
    return "rgba(0,0,0,1)"
}


###################################
# --- Design Constants (Base Canvas Units) ---
# These are defined in original 1080x1920 design space
###################################

$Design = @{
    HeaderY    = -450   # header starting vertical offset
    BodyY      = 250    # body vertical placement offset
    SpacerH    = 60     # spacing between header/body blocks
    SpacerW    = 900    # max text width
    HeaderSize = 90     # font size (header)
    BodySize   = 80     # font size (body)
}


###################################
# --- Motion System ---
# Pixels-per-second movement scaled to resolution
###################################

[int]$PPS  = Scale $PixelsPerSecond
[int]$HPPS = Scale $HeaderPixelsPerSecond


###################################
# --- External Tools ---
###################################

$magick   = "magick.exe"
$ffmpeg   = "ffmpeg.exe"
$OutputDir = "."


###################################
# --- Visual Design Palettes ---
# (kept unchanged from original system)
###################################

$ThemeData = Get-Theme $Theme
$FontColor    = $ThemeData.TextColors


$FontPairs    = $ThemeData.FontPairs| Sort-Object { Get-Random }
$Colors       = $ThemeData.Colors| Sort-Object { Get-Random }
$ShapeColors  = $ThemeData.ShapeColors| Sort-Object { Get-Random }
$HeaderColors = $ThemeData.HeaderColors| Sort-Object { Get-Random }
$Shapes       = $ThemeData.Shapes| Sort-Object { Get-Random }
$ParallaxLayers = $ThemeData.ParallaxLayers

$Quadrants = @("northwest", "northeast", "southwest", "southeast")| Sort-Object { Get-Random }

###################################
# --- Input Validation ---
###################################

if (!(Test-Path $InputFile)) {
    Write-Error "Input file not found!"
    return
}




###################################
# --- Rendering Loop Setup ---
###################################

$count = 0
$totalFrames = $FPS * $DesiredLengthInSeconds


###################################
# --- MUSIC POOL SETUP ---
###################################

$MusicFiles = @()
$MusicIndex = 0

if (![string]::IsNullOrWhiteSpace($Music) -and (Test-Path $Music)) {

    try {
        $Music = (Resolve-Path $Music).Path
    } catch {
        Write-Error "Invalid music path: $Music"
        return
    }
    # Get all audio files (customize extensions as needed)
    $MusicFiles = Get-ChildItem -Path $Music -File | Where-Object {
        $_.Extension -match '\.(mp3|wav|m4a|aac|flac)$'
    }

    if ($MusicFiles.Count -eq 0) {
        Write-Warning "No music files found in folder: $Music"
    } else {
        ##Randomize the music
        $MusicFiles = $MusicFiles | Sort-Object { Get-Random }
        Write-Host "Loaded $($MusicFiles.Count) music files."
    }
}


 



###################################
# --- MAIN PROCESS ---
# Each input line becomes one full video
###################################

Get-Content $InputFile -Encoding UTF8 | ForEach-Object {

    $line = $_.Trim()
    if ($line -eq "") { continue }
    $count++

    # Calculate index based on current line count to loop through arrays
    # Using modulo (%) ensures we never go out of bounds
    $idxFont   = ($count - 1) % $FontPairs.Count
    $idxColor  = ($count - 1) % $Colors.Count
    $idxHColor = ($count - 1) % $HeaderColors.Count
    $idxShape  = ($count - 1) % $Shapes.Count
    $idxSCol   = ($count - 1) % $ShapeColors.Count
    $idxQuad   = ($count - 1) % $Quadrants.Count

    # Select distinct elements
    $SelectedPair = $FontPairs[$idxFont]
    $headerFont   = Protect-MagickText $SelectedPair.Header
    $bodyFont     = Protect-MagickText $SelectedPair.Body

    $headerColor  = $HeaderColors[$idxHColor]
    $bg           = $Colors[$idxColor]
    $grav         = $Quadrants[$idxQuad]
    $shape        = $Shapes[$idxShape]
    $scol         = $ShapeColors[$idxSCol]

    if($ShapeDropShadow)
    {
        #TODO 
        $ShadowColor = Get-ContrastColor $bg  #need the brightness to be opposite of $bg. is bg is light, make shadow dark, if bg is dark, make the shadow light
    }

#######################################
## <<< pre-render the parallax layers
#######################################
$ParallaxTextures = @()

foreach ($layer in $ParallaxLayers) {

    # 1. Determine the size based on the layer depth
    # If your layer has a 'Size' property (e.g., 1, 2, or 3)
    # Disk:1  approx 3x3
    # Disk:2  approx 5x5
    # Disk:4  approx 9x9
    $radius = if ($layer.Size) { $layer.Size } else { 1.5 }

    $pcolor=  Get-ContrastColor $bg

    $file = "parallax_$($layer.Type)_$([guid]::NewGuid().ToString()).png"
##TODO: call Get-ContrastColor on background color

    & $magick `
        -size 2048x2048 xc:black `
        +noise Random `
        -threshold 99% `
        -morphology Dilate "Disk:$radius" `
        -fill "$pcolor" `
        -opaque white `
        -transparent black `
        $file

    $ParallaxTextures += [PSCustomObject]@{
    File  = $file
    Layer = $layer
}
}
    
    $frames = @()


    ###################################
    # --- FRAME RENDER LOOP ---
    ###################################

    for ($i = 0; $i -lt $totalFrames; $i++) {

        $currentTime = $i / $FPS

        # fade-in timing (limits fade to first half or 2 seconds max)
        $TargetFadeSeconds = [Math]::Min(2.0, ($DesiredLengthInSeconds / 2))

        Write-Progress `
            -Activity "Generating Frames for Line $count" `
            -Status "Frame $i of $totalFrames" `
            -PercentComplete (($i / $totalFrames) * 100)

        ###################################
        # --- Motion System ---
        ###################################

        $currentOffset = $PPS * $currentTime
        $headerOffset  = $HPPS * $currentTime

        # shape scaling (slight growth over time for subtle motion)
        #$scaleFactor = 0.95 + ([Math]::Min(0.05, ($currentTime * 0.01)))
        #$resizePercent = [int]($scaleFactor * 100)

        # fade-in opacity curve
        $opacity = [Math]::Min(1.0, ($currentTime / $TargetFadeSeconds))

        # frame naming
        $frame = "frame_{0:D3}_{1:D3}.jpg" -f $count, $i


        ###################################
        # --- ImageMagick Command Build ---
        ###################################

        $magickArgs = @(
            "-quality", "92",
            "-size", "${Width}x${Height}",
            "canvas:$bg"
        )

        ###################################
        #  -->>> It's a parallax, you dig?
        ###################################

        foreach ($p in $ParallaxTextures) {

            $file = $p.File
            $layer = $p.Layer

            $speed = Scale ($PixelsPerSecond * $layer.Speed)
            $px = [int](($speed * $currentTime) % 2048) # 2048 matches your texture size
            $py = [int](($speed * 0.5 * $currentTime) % 2048)

            # $layerW = $Width * 2
            # $layerH = $Height * 2

            $magickArgs += "("
           # $magickArgs += "-size", "${layerW}x${layerH}"
           # $magickArgs += "xc:none"

            $magickArgs += $file
            $magickArgs += "-roll", "+$px+$py"
            #CROP it to the video size so it doesn't overlap weirdly
            $magickArgs += "-crop", "${Width}x${Height}+0+0"

        # apply opacity
            $magickArgs += "-alpha", "set"
            $magickArgs += "-channel", "A"
            $magickArgs += "-evaluate", "multiply", $layer.Opacity
            $magickArgs += "+channel"

            $magickArgs += ")"

            $magickArgs += "-gravity", "center"
            #$magickArgs += "-geometry", "+$px+$py"
            $magickArgs += "-composite"
        }
        ###################################
        # --- SHAPE LAYER ---
        # animated background geometry object (With Shadow & Oscillation)
        ###################################

        
        $geometry = "+$currentOffset+0"#basic init
        switch ($grav) {
            "northwest" { $geometry = "+$currentOffset+$currentOffset" } # Moves Right and Down
            "northeast" { $geometry = "-$currentOffset+$currentOffset" } # Moves Left and Down
            "southwest" { $geometry = "+$currentOffset-$currentOffset" } # Moves Right and Up
            "southeast" { $geometry = "-$currentOffset-$currentOffset" } # Moves Left and Up
        }

        $shapeLayerW = $Width * 3
        $shapeLayerH = $Height * 3

        $offsetX = ($shapeLayerW / 2) - 500
        $offsetY = ($shapeLayerH / 2) - 500


        # 2. Render Shadow (if enabled)
        if ($ShapeDropShadow) {
            $magickArgs += "("
            $magickArgs += "-size", "${shapeLayerW}x${shapeLayerH}"
            $magickArgs += "xc:none"
            $magickArgs += "-fill", $ShadowColor
            $magickArgs += "-gravity", "center"
            # Offset the shadow slightly (Scale 15-20 pixels)
            $sOff = Scale 20
            $magickArgs += "-draw", "translate $($offsetX + $sOff),$($offsetY + $sOff) $shape"
           
            
            #opacity
            $magickArgs += "-alpha", "set"
            $magickArgs += "-channel", "A"
            $magickArgs += "-evaluate", "multiply", $opacity
            $magickArgs += "+channel"
            $magickArgs += ")"

            $magickArgs += "-gravity", "center"
            $magickArgs += "-geometry", $geometry
            $magickArgs += "-composite"
        }


        ###render primary shape
        $magickArgs += "("
        $magickArgs += "-size", "${shapeLayerW}x${shapeLayerH}"#make the shape canvas bigger
        $magickArgs += "xc:none"
        $magickArgs += "-fill", $scol
        $magickArgs += "-gravity", "center"#center the shape on the canvas
        $magickArgs += "-draw", "translate $offsetX,$offsetY $shape"
        #$magickArgs += "-resize", "$resizePercent%"

        # opacity
        $magickArgs += "-alpha", "set"
        $magickArgs += "-channel", "A"
        $magickArgs += "-evaluate", "multiply", $opacity
        $magickArgs += "+channel"
        $magickArgs += ")"

        $magickArgs += "-gravity", "center" # centers the shape canvas on the image
        $magickArgs += "-geometry", $geometry #I do not know what this does
        $magickArgs += "-composite"

        ###################################
        # --- TEXT PROCESSING ---
        # split header/body if ":" exists
        ###################################

        $headerText = ""
        $bodyText = $line

        if ($line -like "*:*") {
            $parts = $line -split ':', 2
            $headerText = Protect-MagickText ($parts[0].Trim() + ":")
            $bodyText   = Protect-MagickText ($parts[1].Trim())
        } else {
            $bodyText = Protect-MagickText $line
        }


        ###################################
        # --- HEADER LAYER ---
        ###################################

        if ($headerText -ne "") {

            $magickArgs += "("
            $magickArgs += "-background", "none"
            $magickArgs += "-fill", "$headerColor"
            $magickArgs += "-font", "$headerFont"
            $magickArgs += "-pointsize", (Scale $Design.HeaderSize)
            $magickArgs += "-size", "$(Scale $Design.SpacerW)x"
            $magickArgs += "caption:$headerText"
            $magickArgs += ")"

            # counter-movement creates parallax effect
            $finalHeaderX = 0 - $headerOffset
            $finalHeaderY = (Scale $Design.HeaderY -Y) - $headerOffset

            $magickArgs += "-gravity", "center"
            $magickArgs += "-geometry", "+$finalHeaderX+$finalHeaderY"
            $magickArgs += "-composite"
        }


        ###################################
        # --- BODY LAYER ---
        # spacer + text stacked vertically
        ###################################

        $sW = Scale $Design.SpacerW
        $sH = Scale $Design.SpacerH

       $magickArgs += "(" 
            # The Spacer: Creates the vertical gap between Header and Body
            $magickArgs += "(" 
                $magickArgs += "-size", "${sW}x${sH}"
                $magickArgs += "canvas:none" 
            $magickArgs += ")"
            
            # The Body Text: Wrapped to the scaled width
            $magickArgs += "("
                $magickArgs += "-background", "none"
                $magickArgs += "-fill", "$FontColor"
                $magickArgs += "-font", "$bodyFont"
                $magickArgs += "-pointsize", (Scale $Design.BodySize)
                $magickArgs += "-size", "${sW}x"
                $magickArgs += "caption:$bodyText"
            $magickArgs += ")"
            
    # Vertically join the spacer and the text
    $magickArgs += "-append"
    $magickArgs += ")"

    # Position the combined block relative to the design center
    $magickArgs += "-gravity", "center"
    $magickArgs += "-geometry", "+0+$(Scale $Design.BodyY -Y)"
    $magickArgs += "-composite"

        ###################################
        # --- DEBUG OUTPUT ---
        ###################################

        Write-Host "--- Frame $i Processing ---" -ForegroundColor Cyan
        Write-Host "Fonts: $headerFont / $bodyFont"
        Write-Host "Colors: BG: $bg | Shape: $scol | Header: $headerColor"
        Write-Host "Shape Movement: $geometry | Header Movement: $finalHeaderX, $finalHeaderY"
        Write-Host "ScaleX=$ScaleX ScaleY=$ScaleY Scale=$Scale"

        Write-Host "FONT CHECK:"
        Test-Path $headerFont
        Test-Path $bodyFont

        Write-Host "FontColor is: $FontColor"

        ###################################
        # --- FINAL FRAME OUTPUT ---
        ###################################

        $magickArgs += $frame
        & $magick $magickArgs

        $frames += $frame
    }


    ###################################
    # --- FFMPEG RENDER STEP ---
    # converts frame sequence → MP4
    ###################################

        $mp4Output = Join-Path $OutputDir ("img_{0:D3}.mp4" -f $count)
        $inputPattern = "frame_{0:D3}_%03d.jpg" -f $count

   
        ###################################
    # --- AUDIO PROCESSING & FFMPEG RENDER ---
    ###################################

       # Initialize audio arguments
    $audioArgs = @()
    $hasAudio = $false


    ##TODO: $Music is now a path to a folder. we want to iterate over the music files in this folder such that each mp4 has a unique music file.
    #if you get to the end of the music files, begin selecting from the top of the music file list again.
        
    if ($MusicFiles.Count -gt 0) {

        # Get current track
        $CurrentMusic = $MusicFiles[$MusicIndex].FullName

        Write-Host "Using music [$MusicIndex]: $CurrentMusic" -ForegroundColor Yellow

        # Prepare ffmpeg input
        $audioArgs += "-stream_loop", "-1", "-i", $CurrentMusic
        $hasAudio = $true

        # Move index forward
        $MusicIndex++

        # Loop back to start if needed
        if ($MusicIndex -ge $MusicFiles.Count) {
            $MusicIndex = 0
        }
    }

    # Combine all arguments for the final render
    $ffmpegArgs = @(
        "-framerate", $FPS,
        "-i", $inputPattern
    )

    # Add audio args if music exists
    if ($hasAudio) {
        $ffmpegArgs += $audioArgs
    }

    $ffmpegArgs += @(
        "-c:v", "libx264",
        "-profile:v", "high",
        "-level:v", "4.1",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-tune", "stillimage",
        "-vf", "pad=ceil(iw/2)*2:ceil(ih/2)*2",
        "-t", $DesiredLengthInSeconds,      # Forces video AND audio to stop exactly here
        "-map", "0:v:0"                      # Use video from first input
    )

    # If music was added, map the audio from the second input
    if ($hasAudio) {
        $ffmpegArgs += "-map", "1:a:0"
        $ffmpegArgs += "-shortest"           # Safety cut to match video length
    }

    $ffmpegArgs += "-movflags", "+faststart"
    $ffmpegArgs += "-g", ($FPS * 2)
    $ffmpegArgs += $mp4Output

    # Execute FFMPEG
    Write-Host "Rendering: $mp4Output" -ForegroundColor Gray
    & $ffmpeg $ffmpegArgs

    ###################################
    # --- CLEANUP / RESULT ---
    ###################################

    if (Test-Path $mp4Output) {

        Write-Host "Success! Generated MP4: $mp4Output" -ForegroundColor Green

        ##call vsign.ps1
        $NewFile = Publish-Video -FullName $mp4Output -Title $Title -MusicName $MusicName -artist "James Barrett"


        if($LASTEXITCODE -eq 0)
        {
            # Delete the individual frames (JPGs)
            $frames | ForEach-Object { Remove-Item $_ -ErrorAction SilentlyContinue }

            # Delete the parallax textures (PNGs)
            $ParallaxTextures | ForEach-Object { Remove-Item $_.File -ErrorAction SilentlyContinue }

            ## make absolutely certain before deleting anything
            if ((Test-Path $NewFile))
            {
                Remove-Item $mp4Output -ErrorAction SilentlyContinue 
            }
        }
    }


}