param (

[Alias("f")]
[ValidateSet("wide","medium","narrow")]
[string]$FOVType = "medium" # Default to medium since it's your preferred setting

)

# Define the lenscorrection parameters for each FOV
$CorrectionParams = @{
    "wide"   = "k1=-0.227:k2=-0.022" # More aggressive to pull in the 170° edges
    "medium" = "k1=-0.18:k2=0.007"  # Your tested 'sweet spot' for 127°
    "narrow" = "k1=-0.05:k2=0.000"  # Minimal correction needed for 90°
}


$selectedParams = $CorrectionParams[$FOVType]



# Get all .mp4 files, excluding already corrected ones
$videos = Get-ChildItem -Filter *.mp4 | Where-Object { $_.Name -notlike "*_corrected.mp4" }

foreach ($video in $videos) {
    $filename = $video.Name
    $output = "$($video.BaseName)_corrected.mp4"
    
    Write-Host "Processing ($FOVType): $filename ..." -ForegroundColor Cyan
    
    # Apply the dynamic parameters to the ffmpeg command
    ffmpeg -i "$filename" -vf "lenscorrection=cx=0.5:cy=0.5:$selectedParams" -c:a copy "$output"
}

Write-Host "Batch Processing Complete for $FOVType FOV!" -ForegroundColor Green


