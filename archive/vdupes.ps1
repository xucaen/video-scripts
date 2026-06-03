param(
    [Parameter(Mandatory = $false)]
    [string]$VideoFolder = ".",           # Defaults to current directory if not provided

    [Parameter(Mandatory = $false)]
    [Alias("f")]
    [string]$FileMask = "clip*.mkv",      # Accept masks like "clip*.mkv"

    [Alias("?", "h")]
    [switch]$Help,

    [double]$SimilarityThreshold = 0.5
)

# ==============================================================================
# HELP MENU
# ==============================================================================
if ($Help) {
    Write-Host @"
Video Duplicate Detector Script
Usage:
  .\script.ps1 -VideoFolder "C:\Videos" -FileMask "clip*.mkv"

Parameters:
  -VideoFolder    Path to your video directory (Defaults to current folder)
  -FileMask (-f)  Filename mask to filter clips (e.g., "clip*.mkv")
  -Help (-h, -?)  Displays this help screen
"@
    Exit
}

# ==============================================================================
# CONFIGURATION & GLOBAL CACHE
# ==============================================================================
$fpcalc = "fpcalc.exe"
$Report = @()
$FingerprintCache = @{} # Caches pre-split arrays: [FullName] -> Array

# ==============================================================================
# FUNCTIONS
# ==============================================================================

# Compares two pre-split arrays directly (Saves massive CPU cycles)
function Get-AudioSimilarity {
    param([array]$Arr1, [array]$Arr2)
    
    if ($null -eq $Arr1 -or $null -eq $Arr2) { return 0.0 }
    
    $MinLength = [System.Math]::Min($Arr1.Count, $Arr2.Count)
    if ($MinLength -eq 0) { return 0.0 }
    
    $Matches = 0
    for ($k = 0; $k -lt $MinLength; $k++) {
        if ($Arr1[$k] -eq $Arr2[$k]) { $Matches++ }
    }
    return ($Matches / $MinLength)
}

# Lazy loader: Only runs fpcalc if we haven't seen this file yet
function Get-OrExtractFingerprint {
    param($File)

    if ($FingerprintCache.ContainsKey($File.FullName)) {
        return $FingerprintCache[$File.FullName]
    }

    $fpcalcArgs = "-raw -length 10 `"$($File.FullName)`""
    
    $ProcessInfo = New-Object System.Diagnostics.ProcessStartInfo -Property @{
        FileName = $fpcalc
        Arguments = $fpcalcArgs
        RedirectStandardOutput = $true
        UseShellExecute = $false
        CreateNoWindow = $true
    }
    
    try {
        $Process = [System.Diagnostics.Process]::Start($ProcessInfo)
        $Output = $Process.StandardOutput.ReadToEnd()
        $Process.WaitForExit()

        if ($Output -match "FINGERPRINT=(.*)") {
            # Parse and split into an array ONCE here
            $Array = $Matches[1].Trim() -split ','
            $FingerprintCache[$File.FullName] = $Array
            return $Array
        }
    } catch {
        Write-Host "[-] Failed running fpcalc on $($File.Name)" -ForegroundColor Red
    }

    $FingerprintCache[$File.FullName] = $null
    return $null
}

function Compare-Group {
    param($List)
    
    if ($List.Count -lt 2) { return }

    Write-Host "Analyzing file pairs..." -ForegroundColor Gray

    # Loop through unique pairs
    for ($i = 0; $i -lt $List.Count; $i++) {
        $FileA = $List[$i]

        for ($j = $i + 1; $j -lt $List.Count; $j++) {
            $FileB = $List[$j]
            
            if (-not (Test-Path $FileA.FullName) -or -not (Test-Path $FileB.FullName)) {
                continue
            }

            # --- GATE 1: LOGICAL TIME SHORT-CIRCUIT ---
            # If they match by time metadata, we don't even need to call fpcalc!
            $TimeMatch = $false
            if ($FileA.ExtractedTime -and $FileB.ExtractedTime) {
                $TimeDiff = [Math]::Abs(($FileA.ExtractedTime - $FileB.ExtractedTime).TotalSeconds)
                $TimeMatch = ($TimeDiff -le 10)
            }

            # --- GATE 2: AUDIO SIMILARITY (LAZY LOADED) ---
            $Similarity = 0.0
            if (-not $TimeMatch) {
                # Fingerprints are only pulled/calculated if the time check didn't already clear them
                $Audio1 = Get-OrExtractFingerprint -File $FileA
                $Audio2 = Get-OrExtractFingerprint -File $FileB

                if ($Audio1 -and $Audio2) {
                    $Similarity = Get-AudioSimilarity -Arr1 $Audio1 -Arr2 $Audio2
                }
            }

            # --- EVALUATION ---
            if ($TimeMatch -or $Similarity -ge $SimilarityThreshold) {
                $PercentDisplay = if ($TimeMatch) { "Time-Match Max" } else { "{0:P0}" -f $Similarity }
                
                $script:Report += " [!] DUPLICATE DETECTED ($PercentDisplay Audio Match)"
                $script:Report += "     Keep: $($FileA.Name)"
                $script:Report += "     Move: $($FileB.Name)"
                
                if (-not (Test-Path $DuplicatesFolder)) {
                    [void](New-Item -ItemType Directory -Path $DuplicatesFolder)
                }

                try {
                    Move-Item -Path $FileB.FullName -Destination $DuplicatesFolder -Force -ErrorAction Stop
                    $script:Report += "     [+] Successfully moved to ./duplicates/"
                } catch {
                    $script:Report += "     [-] Failed to move file: $_"
                }
            } 
        }
    }
}

# ==============================================================================
# SCRIPT EXECUTION
# ==============================================================================
Write-Host "Scanning for videos matching '$FileMask' in: $VideoFolder" -ForegroundColor Cyan

# Gather files and pre-calculate their timestamps immediately to save loop overhead
$Files = Get-ChildItem -Path $VideoFolder -Filter $FileMask -File | ForEach-Object {
    $Time = $null
    if ($_.Name -match '_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})') {
        $Time = [datetime]::ParseExact($Matches[1], 'yyyy-MM-dd_HH-mm-ss', $null)
    }
    $_ | Add-Member -NotePropertyMembers @{ ExtractedTime = $Time } -PassThru
}

if ($Files.Count -lt 2) {
    Write-Host "Found $($Files.Count) file(s). Need at least 2 files to compare." -ForegroundColor Yellow
    Exit
}

Write-Host "Found $($Files.Count) files. Starting pairs comparison..." -ForegroundColor Cyan
Write-Host "--------------------------------------------------------"

$DuplicatesFolder = Join-Path -Path $VideoFolder -ChildPath "duplicates"

Compare-Group -List $Files

Write-Host "----------------------------------------------" -ForegroundColor Cyan
foreach($line in $Report) {
    Write-Host $Line -ForegroundColor Yellow
}
Write-Host "----------------------------------------------" -ForegroundColor Cyan
Write-Host "`nComparison complete." -ForegroundColor Cyan