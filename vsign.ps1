function Publish-Video {
    [CmdletBinding()]
    param (
        [Parameter(Mandatory=$true)]
        [Alias("FullName")]
        [string]$Path,

        [string]$Title = "Untitled",

        [string]$Artist = "",

        [string]$MusicName = "",

        [string]$Year = (Get-Date -Format "yyyy"),

        [string]$Timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
    )

    # 1. Determine Third Party Attribution (Logic moved from your calling script)
    $ThirdParty = if ($MusicName) { 
        "YouTube Audio Library - $MusicName" 
    } else { 
        "Yours Truly most likely" 
    }

    # 2. File Naming Logic
    $fileExtension = [System.IO.Path]::GetExtension($Path)
    $fileNameOnly  = [System.IO.Path]::GetFileNameWithoutExtension($Path)
    $signedFileName = "$($fileNameOnly)_Signed$($fileExtension)"

    # 3. Execute FFmpeg
    # Note: Using -y to overwrite if the signed file already exists
    ffmpeg -i "$Path" -y `
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
        return $signedFileName
    } else {
        Write-Error "FFmpeg failed to sign the file: $Path"
        return $null
    }
}