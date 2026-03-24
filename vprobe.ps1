$files = Get-ChildItem -File | Where-Object { $_.Extension -match "mp4|mkv" -and $_.Name -notmatch "final_output" }
$report = @()

function Convert-FFMpegNumeric($val) {
    if ($val -eq "N/A" -or [string]::IsNullOrWhiteSpace($val)) { return 0 }
    if ($val -match "/") {
        $parts = $val.Split('/')
        if ([double]$parts[1] -eq 0) { return 0 }
        return ([double]$parts[0] / [double]$parts[1])
    }
    return [double]$val
}

foreach ($file in $files) {
    Write-Host "Probing $($file.Name)..." -ForegroundColor Gray
    
    # Get Video Data
    $vRaw = & ffprobe -v error -select_streams v:0 -show_entries stream=duration,nb_frames,r_frame_rate -of csv=p=0 "$($file.FullName)"
    $vParts = $vRaw.Split(',')
    
    # Get Audio Data
    $aRaw = & ffprobe -v error -select_streams a:0 -show_entries stream=duration -of csv=p=0 "$($file.FullName)"
    
    $vDur   = Convert-FFMpegNumeric $vParts[0]
    $vFrame = $vParts[1]
    $vFPS   = Convert-FFMpegNumeric $vParts[2]
    $aDur   = Convert-FFMpegNumeric $aRaw

    $drift = [math]::Round(($vDur - $aDur), 4)
    
    # Determine the culprit
    $issue = "✅ OK"
    if ($vDur -eq 0 -or $aDur -eq 0) { $issue = "❌ BROKEN METADATA" }
    elseif ([math]::Abs($drift) -gt 0.05) { $issue = "⚠️ DRIFTING" }

    $report += [PSCustomObject]@{
        FileName      = $file.Name
        VideoDur      = if ($vDur -eq 0) { "N/A" } else { $vDur }
        AudioDur      = if ($aDur -eq 0) { "N/A" } else { $aDur }
        Drift         = $drift
        FPS           = [math]::Round($vFPS, 2)
        Status        = $issue
    }
}

$report | Format-Table -AutoSize