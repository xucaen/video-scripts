#i2reel.ps1
###Image To Reel
##this script takes all images in current directory
##and turns them into reels

param (
    [int]$FPS = 60,
    [int]$DefaultLengthInSeconds = 15, # Used as a fallback if no audio is present

    [string]$AudioPerClip,
    [switch]$RandomAudio = $false
)

$env:FFREPORT = "file=ffmpeg_crash_log.txt:level=32"
$env:FONTCONFIG_FILE = "nul"
$env:FONTCONFIG_PATH = "nul"
$env:HOME = $PSScriptRoot

# External Scripts & Tools
$SignScript = Join-Path $PSScriptRoot "vsign.ps1"
$ffmpeg = "ffmpeg.exe"
$ffprobe = "ffprobe.exe" # Added for probing audio length
$magick = "magick.exe"
$OutputDir = "."

. $SignScript

# Music Setup
$AudioPerClipFiles = @()
$AudioPerClipIndex = 0
if (![string]::IsNullOrWhiteSpace($AudioPerClip) -and (Test-Path $AudioPerClip)) {
    $AudioPerClipFiles = Get-ChildItem -Path $AudioPerClip -File -Recurse | Where-Object { $_.Extension -match '\.(mp3|wav|m4a|aac|flac)$' } 
    
    if($RandomAudio){
        $AudioPerClipFiles  = $AudioPerClipFiles | Sort-Object { Get-Random }
    }
}

# --- STEP 1: GET ALL IMAGE FILES IN CURRENT DIRECTORY ---
$ImageExtensions = @('.png', '.jpg', '.jpeg', '.webp')
$ImageFiles = Get-ChildItem -Path (Get-Location).Path -File | Where-Object { $ImageExtensions -contains $_.Extension.ToLower() }

if ($ImageFiles.Count -eq 0) {
    Write-Error "No images (.png, .jpg, .jpeg, .webp) found in: $PSScriptRoot"
    exit 1
}

$count = 0

###################################
# --- MAIN PROCESS ---
###################################

foreach ($SourceImage in $ImageFiles) {
    $count++
    $ImageFrameFile = $SourceImage.FullName
    Write-Host "Processing image [$count/${ImageFiles.Count}]: $($SourceImage.Name)" -ForegroundColor Cyan

    # --- STEP 2: DYNAMICALLY GET IMAGE DIMENSIONS ---
    $dimensions = & $magick identify -format "%w,%h" $ImageFrameFile
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrEmpty($dimensions)) {
        Write-Error "Failed to read dimensions for image: $($SourceImage.Name). Skipping."
        continue
    }
    
    $dimArray = $dimensions -split ','
    [int]$ImgWidth  = $dimArray[0]
    [int]$ImgHeight = $dimArray[1]
    
    Write-Host "Detected Dimensions: ${ImgWidth}x${ImgHeight}" -ForegroundColor Magenta

    # --- STEP 4: AUDIO SETUP & DYNAMIC LENGTH CALCULATION ---
    $audioArgs = @()
    $hasAudio = $false
    $DesiredLengthInSeconds = $DefaultLengthInSeconds # Default fallback

    if ($AudioPerClipFiles.Count -gt 0) {
        $CurrentMusic = $AudioPerClipFiles[$AudioPerClipIndex].FullName
        Write-Host "Analyzing audio duration for: $($AudioPerClipFiles[$AudioPerClipIndex].Name)" -ForegroundColor Green
        
        # Call ffprobe to fetch raw duration in seconds
        $RawDuration = & $ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $CurrentMusic
        
        if ($LASTEXITCODE -eq 0 -and ![string]::IsNullOrWhiteSpace($RawDuration)) {
            # Ceiling math ensures we round up to the nearest whole second so audio doesn't get clipped
            $DesiredLengthInSeconds = [Math]::Ceiling([double]$RawDuration)
            Write-Host "Dynamic video length set to match audio: $DesiredLengthInSeconds seconds" -ForegroundColor Green
        } else {
            Write-Warning "Failed to read audio duration. Falling back to default ($DefaultLengthInSeconds seconds)."
        }

        # Removed "-stream_loop -1" since the video length now matches the audio duration perfectly
        $audioArgs = @("-i", $CurrentMusic)
        $hasAudio = $true
        $AudioPerClipIndex = ($AudioPerClipIndex + 1) % $AudioPerClipFiles.Count
    } else {
        Write-Host "No audio files available. Using default length: $DesiredLengthInSeconds seconds" -ForegroundColor Yellow
    }

    # --- STEP 5: FINAL RENDER ---
    $mp4Output = Join-Path $OutputDir ("img_{0:D3}_{1}.mp4" -f $count, $SourceImage.BaseName)

    $totalframes = $FPS * $DesiredLengthInSeconds

    $inputs = @("-y", "-framerate", $FPS, "-loop", "1", "-t", $DesiredLengthInSeconds, "-i", $ImageFrameFile)

    if ($hasAudio) {
        $inputs += $audioArgs
    }

    [double]$Speed = 3.0         
    [double]$zoomFactor = 0.0001
    # Calculate absolute pixel focal points based on the actual image width and height
    [double]$VectorX = Get-Random -Minimum 5 -Maximum ([int]($ImgWidth))
    [double]$VectorY = Get-Random -Minimum 5 -Maximum ([int]($ImgHeight ))

    Write-Host "Chosen Zoom Focal Point: X=$VectorX, Y=$VectorY" -ForegroundColor Cyan

    $zoompanfilter = "zoompan=z='1.0+(on*$Speed*$zoomFactor)':x='$VectorX*(1-1/zoom)':y='$VectorY*(1-1/zoom)':d=1:s=${ImgWidth}x${ImgHeight}:fps=$FPS,scale=${ImgWidth}:${ImgHeight}:flags=bicubic"

    # Use NVENC for the actual encoding step. 
    $ffmpegArgs = $inputs + @(
        "-vf", $zoompanfilter,
        "-c:v", "h264_nvenc",      # Blazing fast hardware encoder
        "-pix_fmt", "yuv420p",     # Standard pixel format that VLC demands
        "-r", $FPS,
        "-frames:v", $totalframes,
        "-t", $DesiredLengthInSeconds
    )

    if ($hasAudio) {
        $ffmpegArgs += @(
            "-map", "0:v:0",   # Explicitly map the video stream
            "-map", "1:a:0",   # Explicitly map the audio stream
            "-shortest"
        )
    }

    $ffmpegArgs += @(
        "-g", ($FPS * 2),                  # Keeps seeking efficient
        "-forced-idr", "1",                # Forces strict hardware IDR frames for faster encoding
        $mp4Output
    )

    Write-Host "Rendering final video: $mp4Output" -ForegroundColor Yellow
    & $ffmpeg $ffmpegArgs

    if (!(Test-Path $mp4Output)) {
        Write-Error "FFmpeg reported success, but $mp4Output is missing!"
        exit 1
    }

    # --- STEP 6: PUBLISH & CLEANUP ---
    $NewFile = Publish-Video -FullName $mp4Output -Title "Video $count" -artist "James Barrett"
    
    if ($null -eq $NewFile -or !(Test-Path $NewFile)) {
        Write-Error "Publish-Video failed to return a valid path. Keeping original files for safety."
        exit 1
    }

    Remove-Item $mp4Output -ErrorAction SilentlyContinue
    Write-Host "Process for image $count complete.`n" -ForegroundColor Gray
}