param (
    [string]$InputFile = "input.txt",
    [int]$Width  = 1440,
    [int]$Height = 1080,
    [string]$Theme = "default",
    [int]$ShapeCount = 11,
    [int]$ShapeLayers = 11
)

$env:FONTCONFIG_FILE = "nul"
$env:FONTCONFIG_PATH = "nul"
$env:HOME = $PSScriptRoot

# External Tools & Paths
$magick = "magick.exe"
$OutputDir = "."

# Design Layout Constants optimized for 1440x1080 (4:3)
$Layout = @{
    HeaderY    = 120     # Pixels from top for header
    BodyY      = 380     # Pixels from top for body text
    SpacerW    = 1240    # Content bounding width
    HeaderSize = 75      # Font size for header
    BodySize   = 55      # Font size for body
}

# Theme Loading
function Get-Theme {
    param([string]$ThemeName)
    $localThemeFolder = Join-Path (Get-Location).Path "themes"
    $themePath = Join-Path $localThemeFolder "$ThemeName.ps1"
    if (!(Test-Path $themePath)) { throw "Theme not found: $ThemeName" }
    return & $themePath 
}

# Initialize Theme Data
$ThemeData    = Get-Theme $Theme
$FontPairs    = $ThemeData.FontPairs | Sort-Object { Get-Random }
$Colors       = $ThemeData.Colors | Sort-Object { Get-Random }
$ShapeColors  = $ThemeData.ShapeColors | Sort-Object { Get-Random }
$HeaderColors = $ThemeData.HeaderColors | Sort-Object { Get-Random }
$Shapes       = $ThemeData.Shapes | Sort-Object { Get-Random }
$FontColor    = $ThemeData.TextColors

$count = 0


function Make-Shape-Layer {
    param(
        [double]$BlurFactor,
        [double]$SizeFactor
    )

    $TempShapeFile = [System.IO.Path]::GetTempFileName() + ".png"



    $ThemeCanvasSize = 1000
    $ScaledCanvasSizeX   = $ThemeCanvasSize / 2
    $ScaledCanvasSizeY    = $ThemeCanvasSize / 2


    $scaleX = ($SizeFactor / $ScaledCanvasSizeX)
    $scaleY = ($SizeFactor / $ScaledCanvasSizeY)

    $lastColor = $null

    $centerX = $Width / 2
    $centerY = $Height / 2
    $goldenAngle = 137.5 * [Math]::PI / 180  # Convert 137.5 degrees to Radians
    $spreadConstant = 500    

    # 1. Start a new isolated layer group so we can transform it together
    $shapeArgs = @(
        "(", 
        "-size", "${Width}x${Height}", 
        "canvas:none"
    )


    for ($i = $ShapeCount; $i -ge 0; $i--){

        # Select a random color distinct from previous
        $availableColors = $ShapeColors | Where-Object { $_ -ne $lastColor }
        $lastColor = $availableColors | Get-Random

        $themeShape = $Shapes | Get-Random

        # Golden Ratio positioning
        $radius = $spreadConstant * [Math]::Sqrt($i)
        $angle  = $i * $goldenAngle

        $translateX = $centerX + ($radius * [Math]::Cos($angle))
        $translateY = $centerY + ($radius * [Math]::Sin($angle))

        # 2. Each shape gets the same size calculation using the SizeFactor knob
        $shapeScaleX = $scaleX
        $shapeScaleY = $scaleY

        # Build clean drawing command (Removed the individual 'rotate' from here)
        $scaledDrawCmd = "push graphic-context translate $translateX,$translateY scale $shapeScaleX,$shapeScaleY translate -$ScaledCanvasSizeX,-$ScaledCanvasSizeY $themeShape pop graphic-context"


        # --- CHANGE 2: INJECT BLUR INTO THE ARGUMENTS ---
        # Add shape to our transparent layer list with the blur applied before the fill/draw
        $shapeArgs += @(
            "-fill", $lastColor,
            "-draw", $scaledDrawCmd
        )
        
    }

    # 3. After ALL shapes are made, apply the same blur to the whole layer
    if ($BlurFactor -gt 0) {
        $shapeArgs += @("-blur", "0x$BlurFactor")
    }



    # Close the layer group and merge (composite) it over the background
    $shapeArgs += @(
        ")"
    )

    # Add output file destination
    $shapeArgs += $TempShapeFile

    # Run the compact shape generation parameters natively
    & $magick "-monitor" $shapeArgs
    return $TempShapeFile
}


function Make-Text-Layer {
    param(
        [string]$HeaderColor,
        [string]$HeaderFont,
        [string]$HeaderText,
        [string]$BodyFont,
        [string]$BodyText
    )

    $TempTextFile = [System.IO.Path]::GetTempFileName() + ".png"

    $textArgs = @(
        "-size", "${Width}x${Height}", 
        "canvas:none",
        
        # --- Header Layer ---
        "(",
            "-background", "none",
            "-fill", $HeaderColor,
            "-font", $HeaderFont,
            "-pointsize", $Layout.HeaderSize,
            "-size", "$($Layout.SpacerW)x${Height}",
            "caption:$HeaderText",
        ")",
        "-gravity", "north",
        "-geometry", "+0+$($Layout.HeaderY)",
        "-composite",

        # --- Body Text Layer ---
        "(",
            "-background", "none",
            "-fill", $FontColor,
            "-font", $BodyFont,
            "-pointsize", $Layout.BodySize,
            "-size", "$($Layout.SpacerW)x${Height}",
            "caption:$BodyText",
        ")",
        "-gravity", "north",
        "-geometry", "+0+$($Layout.BodyY)",
        "-composite",

        $TempTextFile
    )

    & $magick "-monitor" $textArgs
    return $TempTextFile
}




###################################
# --- MAIN PROCESS ---
###################################

Get-Content $InputFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "") { continue }
    $count++

    # Selection Logic per line
    $idxFont   = ($count - 1) % $FontPairs.Count
    $idxColor  = ($count - 1) % $Colors.Count
    $idxHColor = ($count - 1) % $HeaderColors.Count

    $SelectedPair = $FontPairs[$idxFont]
    $headerFont   = $SelectedPair.Header 
    $bodyFont     = $SelectedPair.Body   

    $headerColor  = $HeaderColors[$idxHColor]
    $bg           = $Colors[$idxColor]
  

    # --- TEXT PARSING ---
    $headerText = ""
    $bodyText = $line
    if ($line -like "*:*") {
        $parts = $line -split ':', 2
        $headerText = ($parts[0].Trim() + ":")
        $bodyText   = $parts[1].Trim()
    }

    # Final Output Image Path
    $OutputFile = Join-Path $OutputDir ("img_{0:D3}.png" -f $count)

    Write-Host "Processing Line $count Generating Image..." -ForegroundColor Cyan


# Your initial starting parameters
    [double]$blur   = 30.0
    [double]$size   = 500.0

    $TextImg = Make-Text-Layer -HeaderColor $headerColor -HeaderFont $headerFont -HeaderText $headerText -BodyFont $bodyFont -BodyText $bodyText


    #########################################
    ### ImageMagick Generation Pass
    #########################################
    $magickArgs = @(
        "-monitor",
        "-size", "${Width}x${Height}",
        "canvas:$bg"
    )

    $LayerFiles = @()
    for ($i = 0; $i -lt $ShapeLayers; $i++) {
        
       
        [double]$ratio = if ($ShapeLayers -gt 1) { [double]$i / ([double]$ShapeLayers - 1.0) } else { 0.1 }

        # 2. Blur decreases from 10 down to 0
        $currentBlur = [Math]::Max(0.1, ($blur * (1 - $ratio)))

        # 3. Size decreases but NEVER goes below 1
        $currentSize = [Math]::Max(10.0, ($size - (($size - 10.0) * $ratio)))

           # 5. Call the function using your exact, dynamically scaling values
        $LayerFiles += Make-Shape-Layer -BlurFactor $currentBlur -SizeFactor $currentSize
    }


        $finalArgs = @()
        $finalArgs += $magickArgs

        foreach ($layer in $LayerFiles) {
            $finalArgs += @($layer, "-composite")
        }

        $finalArgs += @($TextImg, "-composite", $OutputFile)

        & $magick "-monitor" $finalArgs
        
}