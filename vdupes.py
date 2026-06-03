import os
import re
import sys
import shutil
import argparse
import fnmatch
import subprocess
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor

# ==============================================================================
# CONFIGURATION
# ==============================================================================
VIDEO_FOLDER = "."
FPCALC_PATH = "fpcalc.exe"
DUPLICATES_FOLDER = os.path.join(VIDEO_FOLDER, "duplicates")

# ==============================================================================
# ARGUMENT PARSING
# ==============================================================================
def parse_arguments():
    parser = argparse.ArgumentParser(
        description="Automated parallel video duplicate detector based on acoustic fingerprinting."
    )
    
    # FILE_MASK is required. If missing, argparse automatically exits with an error.
    parser.add_argument(
        "-f", "--filemask",
        type=str,
        required=True,
        help="Filename mask to filter clips (e.g., 'clip*.mkv' or '*.mp4')"
    )
    
    # SIMILARITY_THRESHOLD is optional and defaults to 0.5 if not provided.
    parser.add_argument(
        "-t", "--threshold",
        type=float,
        default=0.5,
        help="Audio similarity threshold between 0.0 and 1.0 (Default: 0.5)"
    )
    
    return parser.parse_args()

# ==============================================================================
# FUNCTIONS
# ==============================================================================
def extract_timestamp(filename):
    """Extracts yyyy-MM-dd_HH-mm-ss from filename."""
    match = re.search(r'_(\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})', filename)
    if match:
        try:
            return datetime.strptime(match.group(1), '%Y-%m-%d_%H-%M-%S')
        except ValueError:
            return None
    return None

def get_fingerprint(file_path):
    """Invokes fpcalc headless and returns a pre-parsed list of integers."""
    try:
        result = subprocess.run(
            [FPCALC_PATH, "-raw", "-length", "10", file_path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
        )
        match = re.search(r"FINGERPRINT=(.*)", result.stdout)
        if match:
            return [int(x) for x in match.group(1).strip().split(',') if x]
    except Exception as e:
        print(f"[-] Error fingerprinting {file_path}: {e}")
    return None

def get_audio_similarity(arr1, arr2):
    """Calculates array alignment vector similarity at C-speed."""
    if not arr1 or not arr2:
        return 0.0
    min_len = min(len(arr1), len(arr2))
    if min_len == 0:
        return 0.0
    
    matches = sum(1 for x, y in zip(arr1, arr2) if x == y)
    return matches / min_len

# ==============================================================================
# EXECUTION
# ==============================================================================
def main():
    # 1. Parse command line arguments
    args = parse_arguments()
    
    print(f"Scanning for videos matching mask '{args.filemask}' in: {VIDEO_FOLDER}")
    
    # 2. Gather files using standard command-prompt wildcard matching (fnmatch)
    files = [
        f for f in os.listdir(VIDEO_FOLDER) 
        if os.path.isfile(os.path.join(VIDEO_FOLDER, f)) and fnmatch.fnmatch(f, args.filemask)
    ]
    
    # 3. Check if absolutely zero files matched the mask
    if len(files) == 0:
        print(f"Error: No files found matching mask '{args.filemask}' in the directory.")
        sys.exit(1)
        
    # 4. Safety check to ensure there's a pair to compare
    if len(files) < 2:
        print(f"Found {len(files)} file(s). Need at least 2 files to compare.")
        return

    print(f"Found {len(files)} files. Processing fingerprints in parallel...")

    file_paths = [os.path.join(VIDEO_FOLDER, f) for f in files]
    
    # Multi-threaded parallel execution across available CPU cores
    with ThreadPoolExecutor() as executor:
        fingerprints = list(executor.map(get_fingerprint, file_paths))

    # Assemble dataset
    clips = []
    for f, path, fp in zip(files, file_paths, fingerprints):
        clips.append({
            'name': f,
            'path': path,
            'time': extract_timestamp(f),
            'fp': fp
        })

    print("Starting quick-reject pairwise comparison...")
    report = []
    moved_files = set()
    num_files = len(clips)

    for i in range(num_files):
        fileA = clips[i]
        if fileA['path'] in moved_files:
            continue

        for j in range(i + 1, num_files):
            fileB = clips[j]
            if fileB['path'] in moved_files:
                continue

            # GATE 1: Logically check timestamp proximity first
            time_match = False
            if fileA['time'] and fileB['time']:
                time_diff = abs((fileA['time'] - fileB['time']).total_seconds())
                time_match = (time_diff <= 10)

            # GATE 2: Fall back to audio array matching if time gate passes
            similarity = 0.0
            if not time_match and fileA['fp'] and fileB['fp']:
                similarity = get_audio_similarity(fileA['fp'], fileB['fp'])

            # Evaluation
            if time_match or similarity >= args.threshold:
                pct_display = "Time-Match Max" if time_match else f"{similarity:.0%}"
                report.append(f" [!] DUPLICATE DETECTED ({pct_display} Audio Match)\n     Keep: {fileA['name']}\n     Move: {fileB['name']}")
                
                os.makedirs(DUPLICATES_FOLDER, exist_ok=True)
                try:
                    shutil.move(fileB['path'], os.path.join(DUPLICATES_FOLDER, fileB['name']))
                    moved_files.add(fileB['path'])
                    report.append("     [+] Successfully moved to ./duplicates/")
                except Exception as e:
                    report.append(f"     [-] Failed to move file: {e}")

    print("-" * 50)
    for line in report:
        print(line)
    print("-" * 50)
    print("\nComparison complete.")

if __name__ == "__main__":
    main()