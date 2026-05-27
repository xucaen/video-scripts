param (
    [string]$InputFile = "input.txt",
    [int]$Width  = 1080,
    [int]$Height = 1080,
    [string]$Theme = "CyberPastel",
    [int]$ShapeLayers = 11,
    [ValidateSet("golden", "starfield")]
    [string]$SpreadAlgorithm = "golden"    
)

$env:FONTCONFIG_FILE = "nul"
$env:FONTCONFIG_PATH = "nul"
$env:HOME = $PSScriptRoot

function Make-Shape-Layer {
    param(
        [double]$BlurFactor,
        [double]$SizeFactor,
        [int]$ShapeCount,
        [object]$Algorithm
    )

    $TempShapeFile = [System.IO.Path]::GetTempFileName() + ".png"



    $ThemeCanvasSize = 1000
    $ScaledCanvasSizeX   = $ThemeCanvasSize / 2
    $ScaledCanvasSizeY    = $ThemeCanvasSize / 2


    $scaleX = ($SizeFactor / $ScaledCanvasSizeX)
    $scaleY = ($SizeFactor / $ScaledCanvasSizeY)

    $lastColor = $null

    # 1. Jitter the Center Point (Shift by +/- 5% of canvas size)

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

        # 2. Each shape gets the same size calculation using the SizeFactor knob
        $shapeScaleX = $scaleX
        $shapeScaleY = $scaleY

        # --- CREATE THE ANONYMOUS OBJECT PAYLOAD ---
        $algoContext = [PSCustomObject]@{
            Index          = $i
            Width          = $Width
            Height         = $Height
            CenterX        = $Width / 2
            CenterY        = $Height / 2
            SpreadConstant = Get-Random -Minimum 45 -Maximum 250
        }

        $coords = & $ChosenAlgo.Func $algoContext

        # Build clean drawing command (Removed the individual 'rotate' from here)
        $scaledDrawCmd = "push graphic-context translate $($coords.X),$($coords.Y) scale $shapeScaleX,$shapeScaleY translate -$ScaledCanvasSizeX,-$ScaledCanvasSizeY $themeShape pop graphic-context"

        # --- ADDED STROKE SETTINGS ---
        $borderColor = "black"  # Or use a hex code like "#1a1a1a"
        $borderWidth = 3         # Thickness in pixels

        # Add shape to our transparent layer list with fill, stroke, and draw
        $shapeArgs += @(
            "-fill", $lastColor,
            "-stroke", $borderColor,
            "-strokewidth", $borderWidth,
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



function Init-Theme-Data {
    return [PSCustomObject]@{
        Theme_Name    = $Themes.Name
        Font_Pairs    = [PSCustomObject]@{ Header = $Themes.HeaderFont; Body = $Themes.BodyFont }
        Background_Colors   = $Themes.Background 
        Shape_Colors  = $Themes.Shapes
        Header_Colors = $Themes.Headers | Sort-Object { Get-Random }
        Font_Color    = $Themes.Text
    }
}
# Theme Loading
function Get-Theme {
    param(
        [Parameter(Mandatory=$true)]
        [string]$ThemeName
    )

    $localThemeFolder = Join-Path (Get-Location).Path "themes"
    $themePath = Join-Path $localThemeFolder "$ThemeName.ps1"

    if (!(Test-Path $themePath)) { 
        throw "Theme file not found at: $themePath" 
    }

    # Read the file content as a single continuous string
    $rawText = Get-Content -Path $themePath -Raw

    # Evaluate the string directly into a native PowerShell HashTable object
    $themeData = Invoke-Expression $rawText

    return $themeData
}

# External Tools & Paths
$magick = "magick.exe"
$OutputDir = "."

# Design Layout Constants optimized for 1440x1080 (4:3)
$Layout = @{
    HeaderY    = 90     # Pixels from top for header
    BodyY      = 285     # Pixels from top for body text
    SpacerW    = 930    # Content bounding width
    HeaderSize = 56      # Font size for header
    BodySize   = 41      # Font size for body
}


# Initialize Theme Data
$Theme_file_name = "theme2"
$ThemeData    = Get-Theme $Theme_file_name
$Shapes       = $ThemeData.Shapes | Sort-Object { Get-Random }
$AlgorithmRegistry = $ThemeData.AlgorithmRegistry
$ChosenAlgo = $AlgorithmRegistry[$SpreadAlgorithm]
Write-Host "Running generation using: $($ChosenAlgo.Name)" -ForegroundColor Yellow


if ($Theme.ToLower() -eq "random"){
    $Themes = $ThemeData.Themes.Values | Get-Random
}
else {
        #TODO: ensure $Theme is a valid index first
    $Themes = $ThemeData.Themes[$Theme]
}

$data = Init-Theme-Data
$ThemeName    =       $data.Theme_Name            
$FontPairs    =       $data.Font_Pairs    
$Background   =       $data.Background_Colors
$ShapeColors  =       $data.Shape_Colors  
$HeaderColors =       $data.Header_Colors 
$FontColor    =       $data.Font_Color    
####end init theme data

$count = 0

###################################
# --- MAIN PROCESS ---
###################################

Get-Content $InputFile -Encoding UTF8 | ForEach-Object {
    $line = $_.Trim()
    if ($line -eq "") { continue }
    $count++

    #TODO: if $Theme == "random" then call InitThemeData
    if ($Theme.ToLower() -eq "random") {
        $Themes = $ThemeData.Themes.Values | Get-Random
        $data = Init-Theme-Data
        $ThemeName    =       $data.Theme_Name            
        $FontPairs    =       $data.Font_Pairs    
        $Background   =       $data.Background_Colors
        $ShapeColors  =       $data.Shape_Colors  
        $HeaderColors =       $data.Header_Colors 
        $FontColor    =       $data.Font_Color 

        Write-Host "Choosing a new theme: " $ThemeName -ForegroundColor Red -BackgroundColor Cyan
    }

    # Selection Logic per line
    # Safe checks if property is a collection/array or a single string
    $bgCount = $Background.Count
    $hcCount = $HeaderColors.Count

    $idxColor  = ($count - 1) % $bgCount
    $idxHColor = ($count - 1) % $hcCount

    $headerFont   = $FontPairs.Header 
    $bodyFont     = $FontPairs.Body   

    $headerColor  = $HeaderColors[$idxHColor] 
    $bg           = $Background[$idxColor]


    # --- TEXT PARSING ---
    $headerText = ""
    $bodyText = $line
    if ($line -like "*:*") {
        $parts = $line -split ':', 2
        $headerText = ($parts[0].Trim() + ":")
        $bodyText   = $parts[1].Trim()
    }

    # Final Output Image Path (do not overwrite existing files)
    do
    {
        $FilenameID = (Get-Date).ToString("yyyyMMdd_HHmmssff")
        $OutputFile = Join-Path $OutputDir ("img_{0}_{1}.png" -f $ThemeName, $FilenameID )
    }
    while ([System.IO.File]::Exists($OutputFile))

    Write-Host "Processing Line $count Generating Image..." -ForegroundColor Cyan


    # Your initial starting parameters
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
        
        [double]$blur   = Get-Random -Minimum 10 -Maximum 30
        [double]$size   = Get-Random -Minimum 10 -Maximum 250
        [int]$shape_count = Get-Random -Minimum 5 -Maximum 55

       
        [double]$ratio = if ($ShapeLayers -gt 1) { [double]$i / ([double]$ShapeLayers - 1.0) } else { 0.1 }

        # 2. Blur decreases from 10 down to 0
        $currentBlur = [Math]::Max(0.0, ($blur * (1 - $ratio)))

        # 3. Size decreases but NEVER goes below 1
        $currentSize = [Math]::Max(10.0, ($size - (($size - 10.0) * $ratio)))


        # 5. Call the function using your exact, dynamically scaling values
        $LayerFiles += Make-Shape-Layer -BlurFactor $currentBlur -SizeFactor $currentSize -ShapeCount $shape_count
    }


        $finalArgs = @()
        $finalArgs += $magickArgs

        foreach ($layer in $LayerFiles) {
            $finalArgs += @($layer, "-composite")
        }

        $finalArgs += @($TextImg, "-composite", $OutputFile)

        & $magick "-monitor" $finalArgs
        
}