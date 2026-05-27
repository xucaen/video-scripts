param(
    [Alias("i")]
    [string]$ListFile
)

# --- INITIALIZATION ---
# Initializing these at the top ensures the function below can see the $ffprobe path smoothly
$melt = "melt.exe"
$ffprobe = "ffprobe.exe"

# Load your existing vprobe logic
$VprobeScript = Join-Path $PSScriptRoot "vprobe.ps1"
if (Test-Path $VprobeScript) {
    . $VprobeScript
} else {
    Write-Error "Could not find $VprobeScript. Please ensure it is in the same folder."; exit 1
}


function Detect-Silence {

    # --- CONFIGURATION FOR SILENCE DETECTION ---
    $NoiseThreshold = "-30"
    $MinDuration    = "0.5"
    $VideoExtensions = @(".mp4", ".mkv", ".mov", ".avi") # Add any other extensions you use

    # 1. Get all video files in the current folder, sorted by creation date (ascending)
    $VideoFiles = Get-ChildItem -Path (Get-Location) -File | 
    Where-Object { $VideoExtensions -contains $_.Extension.ToLower() } | 
    Sort-Object CreationTime

    if ($null -eq $VideoFiles -or $VideoFiles.Count -eq 0) {
        Write-Error "No matching video files found in the current folder."
        exit 1
    }

    Write-Host "Found $($VideoFiles.Count) videos to process (sorted chronologically)." -ForegroundColor Green
    
    # Track clips globally across all video files processed in this folder pass
    $AllClips = [System.Collections.Generic.List[PSCustomObject]]::new()

    # 2. Master Loop: Process each video file one by one
    foreach ($VideoFile in $VideoFiles) {
        $InputVideo = $VideoFile.FullName
        Write-Host "`n==================================================" -ForegroundColor Yellow
        Write-Host "Analyzing: $($VideoFile.Name) (Created: $($VideoFile.CreationTime))" -ForegroundColor Yellow
        Write-Host "==================================================" -ForegroundColor Yellow

        # Get total duration safely via ffprobe
        $DurationArgs = @("-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", $InputVideo)
        $TotalDurationText = (& $ffprobe $DurationArgs) | Out-String
        $TotalDuration = 0.0
        if (-not [double]::TryParse($TotalDurationText.Trim(), [ref]$TotalDuration)) {
            Write-Warning "Could not determine duration for $($VideoFile.Name). Skipping."
            continue
        }

        # Define the arguments, check voice on track 2
        $FfmpegArgs = @(
            "-i", $InputVideo,
            "-filter_complex", "[0:a:1]silencedetect=noise=${NoiseThreshold}dB:d=$MinDuration",
            "-f", "null", 
            "-"
        )

        # Run ffmpeg, capture stderr, and split by lines for easier parsing later
        $FfmpegLogs = (& ffmpeg $FfmpegArgs 2>&1) | Out-String

        # Parse silence timestamps
        $SilenceMatches = [regex]::Matches($FfmpegLogs, 'silence_start:\s*(?<start>[\d\.]+)|silence_end:\s*(?<end>[\d\.]+)')

        # Build local clips array for this specific video
        $LocalClips = [System.Collections.Generic.List[PSCustomObject]]::new()
        $CurrentStart = 0.0

        foreach ($Match in $SilenceMatches) {
            if ($Match.Groups['start'].Success) {
                $SilenceStart = [double]$Match.Groups['start'].Value
                
                if ($SilenceStart -gt $CurrentStart) {
                    $LocalClips.Add([PSCustomObject]@{
                        File  = $InputVideo
                        Start = [string][Math]::Round($CurrentStart, 2)
                        End   = [string][Math]::Round($SilenceStart, 2)
                    })
                }
            } elseif ($Match.Groups['end'].Success) {
                $CurrentStart = [double]$Match.Groups['end'].Value
            }
        }

        # Catch trailing voice clip
        if ($CurrentStart -lt $TotalDuration) {
            $LocalClips.Add([PSCustomObject]@{
                File  = $InputVideo
                Start = [string][Math]::Round($CurrentStart, 2)
                End   = [string][Math]::Round($TotalDuration, 2)
            })
        }

        if ($LocalClips.Count -eq 0) {
            Write-Host "No voice regions detected in $($VideoFile.Name)." -ForegroundColor Gray
            continue # Moved from 'Exit' to 'continue' so it doesn't kill the script on silent files
        }

        $AllClips.AddRange($LocalClips)
    }

    return $AllClips

} #end Detect-Silence


if ($ListFile) {
    if (-not (Test-Path $ListFile)) {
        Write-Error "List file '$ListFile' not found."; exit 1
    }

    # 1. Import and Clean Data
    $RawData = Import-Csv -Path $ListFile
    $Clips = $RawData | ForEach-Object {
        $CleanRow = [PSCustomObject]@{}
        foreach ($Prop in $_.PSObject.Properties) {
            $CleanRow | Add-Member -MemberType NoteProperty -Name $Prop.Name.Trim() -Value $Prop.Value.Trim().Trim('"')
        }
        $CleanRow
    }
}
else {
    $Clips = Detect-Silence
}

if ($null -eq $Clips -or $Clips.Count -eq 0) {
    Write-Error "No data found to process."; exit 1
}

$ClipNumber = 1

# 2. Main Loop
foreach ($Row in $Clips) {
    try {
        $InputFile = $Row.File
        if (-not (Test-Path $InputFile)) { Write-Warning "Skipping $InputFile (Not found)"; continue }

        # Use your Get-VideoFPS function from vprobe.ps1
        $fps = Get-VideoFPS -FilePath $InputFile
        if ($fps -eq 0) { $fps = 60; Write-Warning "FPS check failed for $InputFile, defaulting to 60" }
        
        # Unifies parsing: checks if string contains a timestamp colon. 
        # If it doesn't, it processes it as raw floating seconds directly.
        if ($Row.Start.Contains(":")) {
            $frameStart = [int]([Timespan]::Parse($Row.Start).TotalSeconds * $fps)
            $frameEnd   = [int]([Timespan]::Parse($Row.End).TotalSeconds * $fps)
        } else {
            $frameStart = [int]([double]$Row.Start * $fps)
            $frameEnd   = [int]([double]$Row.End * $fps)
        }

        # This eliminates the 0 to 0.02 second micro-clips that result in blank outputs.
        if (($frameEnd - $frameStart) -lt 3) {
            Write-Warning "Skipping micro-clip range ($frameStart to $frameEnd) because it's too short to render safely."
            continue
        }
        
        $OutputFile = "Clip_{0:d3}_{1}" -f $ClipNumber, (Get-Item $InputFile).Name

        Write-Host "`n--- Processing Clip #$ClipNumber ---" -ForegroundColor Cyan
        Write-Host "Source: $InputFile ($fps fps)"
        Write-Host "Range:  $($Row.Start) ($frameStart) to $($Row.End) ($frameEnd)"
        Write-Host "Output: $OutputFile"

        # 3. Arguments for Start-Process
        $meltArgs = @(
            "`"$InputFile`"", 
            "in=$frameStart",
            "out=$frameEnd",
            "-consumer", "avformat:`"$OutputFile`"",
            "vcodec=libx264",
            "acodec=aac",
            "crf=18",
            "terminate=1",
            "-silent"
        )

        # 4. EXECUTE WITH PROCESS CONTROL
        $proc = Start-Process -FilePath $melt -ArgumentList $meltArgs -Wait -NoNewWindow -PassThru

        if ($proc.ExitCode -eq 0) { 
            Write-Host "Success!" -ForegroundColor Green
            $ClipNumber++ 
        } else {
            Write-Host "Melt failed with exit code $($proc.ExitCode)" -ForegroundColor Red
        }
    }
    catch {
        Write-Host "Failed to process row: $($_.Exception.Message)" -ForegroundColor Red
    }
}

Write-Host "`nDone! Created $($ClipNumber - 1) clips." -ForegroundColor Green