param(
    [Alias("i")]
    [string]$ListFile
)

# --- INITIALIZATION ---
$melt = "melt.exe"
$ffprobe = "ffprobe.exe"

# Load your existing vprobe logic
$VprobeScript = Join-Path $PSScriptRoot "vprobe.ps1"
if (Test-Path $VprobeScript) {
    . $VprobeScript
} else {
    Write-Error "Could not find $VprobeScript. Please ensure it is in the same folder."; exit 1
}

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

if ($null -eq $Clips -or $Clips.Count -eq 0) {
    Write-Error "No data found in $ListFile"; exit 1
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
        
        $frameStart = [int]([Timespan]::Parse($Row.Start).TotalSeconds * $fps)
        $frameEnd   = [int]([Timespan]::Parse($Row.End).TotalSeconds * $fps)

        $OutputFile = "Clip_{0:d3}_{1}" -f $ClipNumber, (Get-Item $InputFile).Name

        Write-Host "`n--- Processing Clip #$ClipNumber ---" -ForegroundColor Cyan
        Write-Host "Source: $InputFile ($fps fps)"
        Write-Host "Range:  $($Row.Start) ($frameStart) to $($Row.End) ($frameEnd)"
        Write-Host "Output: $OutputFile"

        # 3. Arguments for Start-Process
        # We pass these as a clean array. Start-Process handles the quoting for us.
        $meltArgs = @(
            "$InputFile",
            "in=$frameStart",
            "out=$frameEnd",
            "-consumer", "avformat:$OutputFile",
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