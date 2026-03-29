# --- vprobe.ps1 ---
function Get-VideoFPS {
    param([string]$FilePath)
    try {
        # Using -LiteralPath style for ffprobe
        $rawJson = & ffprobe -v error -select_streams v:0 -show_entries stream=avg_frame_rate -of json "$FilePath"
        
        if ([string]::IsNullOrWhiteSpace($rawJson)) { return 0 }
        
        $probe = $rawJson | ConvertFrom-Json
        
        # Guard against files with no video streams
        if ($null -eq $probe.streams -or $probe.streams.Count -eq 0) { return 0 }
        
        $rawFPS = $probe.streams[0].avg_frame_rate # This will be something like "30/1"

        if ($rawFPS -match "/") {
            $parts = $rawFPS.Split('/')
            if ([double]$parts[1] -ne 0) {
                return [math]::Round(([double]$parts[0] / [double]$parts[1]), 2)
            }
        }
        return [double]$rawFPS
    }
    catch {
        return 0
    }
}




# --- REPORT LOGIC (Only runs when called directly) ---
if ($MyInvocation.InvocationName -notmatch '\. ' -and $MyInvocation.InvocationName -ne '.') {
    $files = Get-ChildItem -File | Where-Object { $_.Extension -match "mp4|mkv" -and $_.Name -notmatch "final_output" }
    $report = foreach ($file in $files) {
        Write-Host "Probing $($file.Name)..." -ForegroundColor Gray
        
        $vProbe = & ffprobe -v error -select_streams v:0 -show_entries stream=duration -of json "$($file.FullName)" | ConvertFrom-Json
        $vDur = if ($vProbe.streams[0].duration) { [double]$vProbe.streams[0].duration } else { 0 }

        $aProbe = & ffprobe -v error -select_streams a:0 -show_entries stream=duration -of json "$($file.FullName)" | ConvertFrom-Json
        $aDur = if ($aProbe.streams[0].duration) { [double]$aProbe.streams[0].duration } else { 0 }

        $vFPS = Get-VideoFPS -FilePath $file.FullName
        $drift = [math]::Round(($vDur - $aDur), 4)

        [PSCustomObject]@{
            FileName = $file.Name
            VideoDur = if ($vDur -eq 0) { "N/A" } else { $vDur }
            AudioDur = if ($aDur -eq 0) { "N/A" } else { $aDur }
            Drift    = $drift
            FPS      = $vFPS
            Status   = if ($vDur -eq 0) { "❌ BROKEN" } elseif ([math]::Abs($drift) -gt 0.05) { "⚠️ DRIFTING" } else { "✅ OK" }
        }
    }
    $report | Format-Table -AutoSize
}