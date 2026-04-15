param(
    # Number of clips per output file. 0 merges everything into one.
    [Alias("c")]
    [int]$ChunkSize = 0,

    # Transition Duration in seconds.
    [Alias("d")]
    [double]$TransitionDuration = 0.5,

    # The style of transition (MLT / melt transitions).
    # Options:
    #   mix   = standard dissolve
    #   luma  = smooth fade using luma blending
    #   wipe  = wipe-style transition (basic luma wipe)
    [Alias("t")]
    [ValidateSet("mix","luma","wipeh", "wipev")]
    [string]$TransitionType = "mix",

    # Path to Intro video
    [Alias("i")]
    [string]$Intro,

    # Path to Outro video
    [Alias("u")]
    [string]$Outro,

    #number of seconds to cut off the front of the clip
    ###### Do NOT cut off the front of the Intro or Outro ######
    [Alias("tf")]
    [int]$TrimFront = 0,

    #randomize the order of clips to be joined
    #ignore if chunksize < 2
    [Alias("r")]
    [switch]$Random,

    #passthru for Publish-Video
    [string]$Title,

    # Help System.
    [Alias("?", "h")]
    [switch]$Help
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
# --- HELP DISPLAY ---
if ($Help) {
    Write-Host @"

VMELT.PS1 - Video Merge Utility with Transitions (MELT Edition)
--------------------------------------------------
Merges video clips in the current directory using melt (MLT framework).

USAGE:
  .\vmelt.ps1 [-c ChunkSize] [-d Duration] [-t Transition type] [-?]

PARAMETERS:
  -c, -chunksize  Number of clips per output file. 
                  (Default: 0 - Merges all clips into one file)

  -d, -duration   Duration of the transition in seconds.
                  (Default: 0.5)

  -t, -transition Type of transition.
                  Options: mix, luma, wipeh, wipev.
                  (Default: mix)

  -tf, -trimfront number of seconds to cut off the front of the clip
                    Does NOT cut off the front of the Intro or Outro
                  (default: 0)

   -r, -random    Randomize the order of clips to be joined
                  Note: Is ignored if chunksize < 2
    
  -?, -help       Displays this help message.

EXAMPLES:
  .\vmelt -c 5 -d 1.0 -t luma
  .\vmelt -?

"@ -ForegroundColor White
    exit 0
}

function Shuffle {
    param($List )
   #shuffle the order of $list and return the shuffled list
   return $List | Get-Random -Count $List.Count
}


# --- SETTINGS & INITIALIZATION ---
$melt = "melt.exe"
$ffmpeg = "ffmpeg.exe"
$vprobe = "C:/PROJECTS/POWERSHELL/VIDEO SCRIPTS/vprobe.ps1"
$transitionDur = $TransitionDuration
$transitionTyp = $TransitionType

### Validate Intro/Outro paths if provided
if ($Intro -and !(Test-Path $Intro)) { Write-Host "Intro file not found: $Intro" -ForegroundColor Red; exit 1}
if ($Outro -and !(Test-Path $Outro)) { Write-Host "Outro file not found: $Outro" -ForegroundColor Red; exit 2}



### Identify raw clips
$sourceFiles = Get-ChildItem -Path (Get-Location) -File | Where-Object {
    ($_.Extension -eq ".mp4" -or $_.Extension -eq ".mkv") -and
    ($_.Name -notmatch "final_output") -and ($_.Name -notmatch "temp") -and
    ($_.DirectoryName -notmatch "_vmelt_temp")
} | Sort-Object { [regex]::Replace($_.Name,'\d+',{ $args.Value.PadLeft(20,'0') }) }

$totalClips = $sourceFiles.Count
if ($totalClips -eq 0) { 
    Write-Host "No video clips found!" -ForegroundColor Red
    exit 3
}




# ---  CHUNK & MANIFEST GENERATION ---
if ($ChunkSize -le 0) { 
    $ChunkSize = $totalClips 
}





### Use source files directly (no normalization)
#if $Random is on, shuffle these $sourceFiles into a randomized order
#ignore $Random if chunksize < 2
if ($Random -and ($ChunkSize -gt 1))
{
    #shuffle these $sourceFiles into a randomized order and place into $normalizedFiles
   $normalizedFiles = Shuffle($sourceFiles)
}
else {
   $normalizedFiles = $sourceFiles
}



$numBatches = [Math]::Ceiling($totalClips / $ChunkSize)

for ($b = 0; $b -lt $numBatches; $b++) {
    $batchNum = ($b + 1).ToString("D2")
    $batchFile = "batch_$batchNum.txt"
    $startIndex = $b * $ChunkSize
    $currentBatchClips = $normalizedFiles | Select-Object -Skip $startIndex -First $ChunkSize
    
    $lines = @()

    # Insert Intro if defined
    if ($Intro) { $lines += (Get-Item $Intro).FullName }
    
    # ADDING MAIN CLIPS
    foreach ($clip in $currentBatchClips) { $lines += $clip.FullName }

    # Append Outro if defined
    if ($Outro) { $lines += (Get-Item $Outro).FullName }

    $lines | Set-Content $batchFile
    Write-Host "Created $batchFile with $($lines.Count) entries." -ForegroundColor Blue
}

# ---  USER VERIFICATION ---
Write-Host "`n--- QUEUE READY FOR INSPECTION ---" -ForegroundColor Cyan
Get-ChildItem -Path "batch_*.txt" | Select-Object -Property Name


Write-Host "`nTransition: $transitionTyp ($($transitionDur)s)" -ForegroundColor Yellow
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

            
        if (-$fps -eq 0) {
            Write-Host "Could not detect FPS for $firstClip, defaulting to 30" -ForegroundColor Yellow
            $fps = 30
        }
        
    
    # Round to nearest whole number for the Melt Profile name if needed, 
    # but keep the decimal for frame math.
    $roundedFps = [Math]::Round($fps)
    Write-Host "Detected FPS: $fps (Using $roundedFps for Profile)" -ForegroundColor Cyan

    $mixFrames = [int]($transitionDur * $fps)  
    $trimFrames = [int]($TrimFront * $fps)

    $batchNum = $file.Name.Replace("batch_","").Replace(".txt","")
    $outputName = "final_output_$batchNum.mp4"

    Write-Host "Encoding batch $batchNum to $outputName using MELT..." -ForegroundColor Yellow

    ################################################################
    # MELT TIMELINE BUILD
    ################################################################

    $meltArgs = @()

    $introPath = if ($Intro) { (Get-Item $Intro).FullName } else { $null }
    $outroPath = if ($Outro) { (Get-Item $Outro).FullName } else { $null }

    for ($i = 0; $i -lt $inputFiles.Count; $i++) {
        $clip = $inputFiles[$i]

        $isIntro = ($clip -eq $introPath)
        $isOutro = ($clip -eq $outroPath)

        $useTrim = $false

        if ($TrimFront -gt 0 -and -not $isIntro -and -not $isOutro) {

            $durationOutput = & $ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1:nokey=1 $clip
            $duration = [double]$durationOutput

            if ($TrimFront -lt $duration) {
                $useTrim = $true
            } else {
                Write-Host "Trim exceeds clip length, using full clip: $clip" -ForegroundColor DarkYellow
            }
        }

        if ($useTrim) {
            $meltArgs += "`"$clip`""
            $meltArgs += "in=$trimFrames"
        } else {
            $meltArgs += "`"$clip`""
        }

        if ($i -gt 0) {

            if($isOutro){ continue }

            switch ($transitionTyp) {

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

    $meltArgs += "-silent"


    $meltProcess = Start-Process -FilePath $melt -ArgumentList $meltArgs -Wait -NoNewWindow -PassThru

    if ($meltProcess.ExitCode -ne 0) {
        Write-Host "MELT had a meltdown. " -ForegroundColor RED -BackgroundColor White
        write-Host "---------`$meltArgs---------------" -ForegroundColor GREEN -BackgroundColor BLACK
        write-Host "$meltArgs" -ForegroundColor GREEN -BackgroundColor BLACK
        write-Host "-----------------------------------" -ForegroundColor GREEN -BackgroundColor BLACK
        exit 4
    }

    $ffmpegArgs = "-i temp.mkv -c:v h264_nvenc -preset p5 -rc vbr -cq 19 -c:a copy `"$outputName`""

    $ffmpegProcess = Start-Process -FilePath $ffmpeg -ArgumentList $ffmpegArgs -Wait -NoNewWindow -PassThru

    if ($ffmpegProcess.ExitCode -ne 0) {
        Write-Host "FFMPEG failed. " -ForegroundColor Magenta -BackgroundColor White
        exit 5
    }

     ##call vsign.ps1
        Publish-Video -FullName $outputName -Title $Title -artist "James Barrett"

}

Write-Host "`nALL DONE! Check your final_output files." -ForegroundColor Green