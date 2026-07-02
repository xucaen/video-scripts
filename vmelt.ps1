param(
    # Time ceiling in seconds per output file. 0 merges everything into one.
    [Alias("s")]
    [double]$MaxBatchDurationSeconds = 15.0,

    # Transition Duration in seconds.
    [Alias("d")]
    [double]$TransitionDuration = 0.5,

    # The style of transition (MLT / melt transitions).
    # Options:
    #   mix   = standard dissolve
    #   luma  = smooth fade using luma blending
    #   wipe  = wipe-style transition (basic luma wipe)
    [Alias("t")]
    [ValidateSet("mix","luma","wipeh", "wipev", "cut")]
    [string]$TransitionType = "mix",

    # Path to Intro video
    [Alias("i")]
    [string]$IntroPath,

    # Path to Outro video
    [Alias("u")]
    [string]$OutroPath,

    # randomize the order of clips to be joined
    [Alias("r")]
    [switch]$Random,

    # passthru for Publish-Video
    [string]$Title,

    [ValidateSet("name","timestamp")]
    [string]$SortBy = "name"

)

########################################
## "include" files
########################################

$SignScript = Join-Path $PSScriptRoot "vsign.ps1"
. $SignScript

$VprobeScript = Join-Path $PSScriptRoot "vprobe.ps1"
. $VprobeScript

if (-not (Get-Command Publish-Video -ErrorAction SilentlyContinue)) {
    Write-Error "The file $SignScript loaded, but it doesn't contain the 'Publish-Video' function!"
    exit
}


[switch]$FullClip = $false

########################################
## Helper Functions
########################################

function Shuffle {
    param($List)
    return $List | Get-Random -Count $List.Count
}

function Get-ClipDuration {
    param([string]$FilePath)

    $out = & $ffprobe -v error -show_entries format=duration `
        -of default=noprint_wrappers=1:nokey=1 "$FilePath"

    return [double]$out
}

function Build-TimeBatches {
    param(
        [array]$Files,
        [double]$MaxSeconds,
        [switch]$full_clip
    )

    $batches = @()
    $currentBatch = @()
    $currentTime = 0.0

        if($full_clip) 
        {
           $batches += ,$Files
            return ,$batches
            
        }

    foreach ($file in $Files) {
        $duration = Get-ClipDuration -FilePath $file.FullName


        # Edge case: single clip longer than max
        if ($duration -ge $MaxSeconds -and $currentBatch.Count -eq 0) {
            $batches += ,@($file)
            continue
        }

        # If adding this clip exceeds limit -> flush batch
        if (($currentTime + $duration) -gt $MaxSeconds -and $currentBatch.Count -gt 0) {
            $batches += ,$currentBatch
            $currentBatch = @()
            $currentTime = 0.0
        }

        $currentBatch += $file
        $currentTime += $duration
    }

    # Flush remaining
    if ($currentBatch.Count -gt 0) {
        $batches += ,$currentBatch
    }

    return $batches
}

function Get-FFMpegArgs {
    param(
        [string]$OutputName,
        [string]$FFprobePath
    )


    $ffmpegArgs = $null


    $ffmpegArgs = "-i temp.mkv -c:v h264_nvenc -preset p5 -rc vbr -cq 19 -c:a copy `"$OutputName`""

    return $ffmpegArgs
}

function Get-Sorted-List {
    [CmdletBinding()]
    param (
        [string]$SortBy 
    )

    ### Identify raw clips
    $rawFiles = Get-ChildItem -Path (Get-Location) -File | Where-Object {
        ($_.Extension -eq ".mp4" -or $_.Extension -eq ".mkv") -and
        ($_.Name -notmatch "final_output") -and ($_.Name -notmatch "temp") -and
        ($_.DirectoryName -notmatch "_vmelt_temp")
    }

    # Regex pattern for (yyyy-MM-dd_hh-mm-ss) allowing space or underscore
    $timestampPattern = '\d{4}-\d{2}-\d{2}[ _]\d{2}-\d{2}-\d{2}'

    if ($SortBy -eq "timestamp") {
        # Check if ANY file is missing the timestamp
        foreach ($file in $rawFiles) {
            if ($file.Name -notmatch $timestampPattern) {
                Write-Error "Error: The file '$($file.Name)' does not contain a valid timestamp (yyyy-MM-dd_hh-mm-ss)."
                return $null 
            }
        }

        # Sort with a tie-breaker: Primary = normalized timestamp, Secondary = natural filename sort
        $rawFiles | Sort-Object { 
            if ($_.Name -match $timestampPattern) { 
                # Replace space/underscore with a generic dash so they string-compare perfectly
                $_.Name -match $timestampPattern | Out-Null
                $Matches[0] -replace '[ _]', '-' 
            } 
        }, { 
            # Secondary tie-breaker: natural sort padding logic for the suffix (Clip_001, zoom, etc.)
            [regex]::Replace($_.Name, '\d+', { $args.Value.PadLeft(20, '0') }) 
        }
    }
    else {
        # Default: Sort by Name (using natural sort padding logic) and output
        $rawFiles | Sort-Object { [regex]::Replace($_.Name, '\d+', { $args.Value.PadLeft(20, '0') }) }
    }
}

# --- SETTINGS & INITIALIZATION ---
$melt = "melt.exe"
$ffmpeg = "ffmpeg.exe"
$ffprobe = "ffprobe.exe"
[double]$transitionDur = $TransitionDuration
$transitionTyp = $TransitionType

### Validate Intro/Outro paths if provided


if ($IntroPath -and !(Test-Path $IntroPath)) { Write-Host "Intro Folder not valid: $IntroPath" -ForegroundColor Red; exit 1}
if ($OutroPath -and !(Test-Path $OutroPath)) { Write-Host "Outro Folder not found: $OutroPath" -ForegroundColor Red; exit 2}

#Get List of clips from the $IntroPath folder
if ($IntroPath -and (Test-Path $IntroPath)) 
{
    $IntroList = Get-ChildItem -Path $IntroPath -File | Where-Object { $_.Extension -in ".mp4", ".mkv" } | Sort-Object Name
}

if ($OutroPath -and (Test-Path $OutroPath)) 
{ 
    $OutroList = Get-ChildItem -Path $OutroPath -File | Where-Object { $_.Extension -in ".mp4", ".mkv" } | Sort-Object Name
}


### Identify raw clips
$sourceFiles = Get-Sorted-List -SortBy $SortBy

$totalClips = $sourceFiles.Count
if ($totalClips -eq 0) { 
    Write-Host "No video clips found!" -ForegroundColor Red
    exit 3
}

# Fallback scenario: if MaxBatchDuration is configured to 0 or less, bundle all clips into an arbitrarily massive window
if ($MaxBatchDurationSeconds -le 0) { 
    $FullClip = $true
}

### Use source files directly (handle randomization shuffling)
if ($Random) {
    $normalizedFiles = Shuffle($sourceFiles)
}
else {
    $normalizedFiles = $sourceFiles
}

# --- GENERATE TIME-BASED BATCHES ---
$batches = Build-TimeBatches -Files $normalizedFiles -MaxSeconds $MaxBatchDurationSeconds -full_clip $FullClip



for ($b = 0; $b -lt $batches.Count; $b++) {
    $batchNum = ($b + 1).ToString("D2")
    $batchFile = "batch_$batchNum.txt"
    $currentBatchClips = $batches[$b]
    
    $lines = @()

    # Insert Intro if defined
    #prepend the list of intro clips
    foreach($i in $IntroList)
    {
        $lines += $i.FullName
    }

    # ADDING MAIN CLIPS
    foreach ($clip in $currentBatchClips) { $lines += $clip.FullName }

    # Append Outro if defined
    foreach($o in $OutroList)
    {
        $lines += $o.FullName
    }


    $lines | Set-Content $batchFile
    Write-Host "Created $batchFile with $($currentBatchClips.Count) core clips." -ForegroundColor Blue
}

# --- USER VERIFICATION ---
Write-Host "`n--- QUEUE READY FOR INSPECTION ---" -ForegroundColor Cyan
Get-ChildItem -Path "batch_*.txt" | Select-Object -Property Name

[double]$displayDur = $transitionDur;
if($transitionTyp -eq "cut") {
    $displayDur = 0.0
}
Write-Host "`nTransition: $transitionTyp ($($displayDur)s)" -ForegroundColor Yellow
Read-Host "Edit .txt files if needed, then Press Enter to begin encoding"

# --- MAIN ENCODING LOOP (MELT IMPLEMENTATION) ---
$manifests = Get-ChildItem "batch_*.txt" | Sort-Object Name

# Path to the luma assets based on your directory listing
$lumaRepo = "C:\\Program Files\\kdenlive\\bin\\data\\kdenlive\\lumas\\HD"

#############################
# --- MAIN LOOP ---
##############################
foreach ($file in $manifests) {
    $inputFiles = Get-Content $file.FullName
    if ($inputFiles.Count -eq 0) { continue }

    # Convert transition duration (seconds -> frames)
    # --- 1. PROBE FIRST CLIP FOR FPS ---
    $firstClip = $inputFiles[0]
    $fps = Get-VideoFPS -FilePath $firstClip

    # Round to nearest whole number for the Melt Profile name if needed, 
    # but keep the decimal for frame math.
    $roundedFps = [Math]::Round($fps)
    Write-Host "Detected FPS: $fps (Using $roundedFps for Profile)" -ForegroundColor Cyan

    $mixFrames = [int]($transitionDur * $fps)  


    $batchNum = $file.Name.Replace("batch_","").Replace(".txt","")

    ################################################################
    # MELT TIMELINE BUILD
    ################################################################

    $meltArgs = @()

    for ($i = 0; $i -lt $inputFiles.Count; $i++) {
        $clip = $inputFiles[$i]

        $meltArgs += "`"$clip`""

        if ($i -gt 0) {

            switch ($transitionTyp) {
                "cut" {
                    # do nothing, just pass thru the clip
                }
                "mix" {
                    # Standard dissolve
                    $meltArgs += "-mix"
                    $meltArgs += "$mixFrames"
                }
                "luma" {
                    # Smooth fade
                    $meltArgs += "-mix"
                    $meltArgs += "$mixFrames"
                    $meltArgs += "-mixer"
                    $meltArgs += "luma"
                }
                "wipeh" {
                    # A geometric wipe using a PGM resource
                    $pattern = Join-Path $lumaRepo "bi-linear_x.pgm"
                    $meltArgs += "-mix"
                    $meltArgs += "$mixFrames"
                    $meltArgs += "-mixer"
                    $meltArgs += "luma"
                    $meltArgs += "resource=`"$pattern`""
                }
                "wipev" {
                    # A geometric wipe using a PGM resource
                    $pattern = Join-Path $lumaRepo "bi-linear_y.pgm"
                    $meltArgs += "-mix"
                    $meltArgs += "$mixFrames"
                    $meltArgs += "-mixer"
                    $meltArgs += "luma"
                    $meltArgs += "resource=`"$pattern`""
                }
            }
        }
    }

    ################################################################
    # OUTPUT SETTINGS
    ################################################################

    $meltArgs += "-consumer"
    $meltArgs += "avformat:temp.mkv"

    $meltArgs += "vcodec=libx264"
    $meltArgs += "crf=0"
    $meltArgs += "acodec=aac"
    $meltArgs += "ab=192k"        # Explicitly set Melt's audio bitrate
    $meltArgs += "ar=48000"       # Force Melt to mix down everything to 48kHz

    $meltArgs += "-silent"

    $meltProcess = Start-Process -FilePath $melt -ArgumentList $meltArgs -Wait -NoNewWindow -PassThru

    if ($meltProcess.ExitCode -ne 0) {
        Write-Host "MELT had a meltdown. " -ForegroundColor RED -BackgroundColor White
        Write-Host "---------`$meltArgs---------------" -ForegroundColor GREEN -BackgroundColor BLACK
        Write-Host "$meltArgs" -ForegroundColor GREEN -BackgroundColor BLACK
        Write-Host "-----------------------------------" -ForegroundColor GREEN -BackgroundColor BLACK
        exit 4
    }

    $outputName = "final_output_$((Get-Date).ToString('yyyy-MM-dd_HH-mm-ss')).mp4"
    Write-Host "Encoding batch $batchNum to $outputName using MELT..." -ForegroundColor Yellow
    
    $ffmpegArgs = Get-FFMpegArgs -OutputName $outputName -FFprobePath $ffprobe

    $ffmpegProcess = Start-Process -FilePath $ffmpeg -ArgumentList $ffmpegArgs -Wait -NoNewWindow -PassThru

    if ($ffmpegProcess.ExitCode -ne 0) {
        Write-Host "FFMPEG failed. " -ForegroundColor Magenta -BackgroundColor White
        exit 5
    }

    ## call vsign.ps1
    $signedFileName = Publish-Video -FullName $outputName -Title $Title -artist "James Barrett"
    # Check if the signed file exists using Test-Path
    if (Test-Path -Path $signedFileName){
        Remove-Item -Path $outputName
    }
}

Write-Host "`nALL DONE! Check your final_output files." -ForegroundColor Green