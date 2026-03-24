param (
    [Parameter(Mandatory=$true)]
    [string]$Path,

    [Parameter(Mandatory=$true)]
    [string]$Title,

    [string]$Artist = "James Barrett",

    [string]$ThirdParty = "",
    
    [string]$Year = (Get-Date -Format "yyyy"),

    [string]$Timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
)

# Define the output filename (e.g., TrackName_Signed.mp4)
if ([string]::IsNullOrWhiteSpace($Title)) {
    $Title = "Untitled"
}
$fileExtension = [System.IO.Path]::GetExtension($Path)
$fileNameOnly  = [System.IO.Path]::GetFileNameWithoutExtension($Path)
$signedFileName = "$($fileNameOnly)_Signed$($fileExtension)"

# Execute FFmpeg
ffmpeg -i "$Path" `
    -metadata title="$Title" `
    -metadata artist="$Artist" `
    -metadata author="$Artist" `
    -metadata composer="$ThirdParty" `
    -metadata copyright="© $Year $Artist. All rights reserved." `
    -metadata creation_time="$Timestamp" `
    -metadata comment="Original work created via Scarlett Solo, Audacity, Melt, ffmpeg, and my imagination." `
    -codec copy "$signedFileName"

if ($LASTEXITCODE -eq 0) {
    Write-Host "Successfully signed: $signedFileName" -ForegroundColor Green
} else {
    Write-Error "FFmpeg failed sign the file." -ForegroundColor Magenta -BackgroundColor White
}