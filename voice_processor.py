import argparse
import os
import wave
import numpy as np
from scipy.signal import lfilter, butter

def parse_parameters():
    parser = argparse.ArgumentParser(description="Post-Op Voice Processing Suite for Windows 11")
    parser.add_argument("-i", "--input", required=True, help="Path to input .wav file")
    parser.add_argument("--speed", type=float, default=1.0, help="Speed multiplier (e.g. 1.0 = normal, 1.1 = 10%% faster)")
    parser.add_argument("--pitch", type=float, default=1.0, help="Pitch multiplier (e.g. 0.9 = deeper, 1.1 = higher)")
    parser.add_argument("--eq", type=float, nargs=5, default=[0.0, 0.0, 0.0, 0.0, 0.0], help="5-Band EQ gains in dB for bands: 80Hz, 250Hz, 1kHz, 4kHz, 12kHz")
    parser.add_argument("--gate", type=float, default=-50.0, help="Noise gate threshold in dB (e.g. -40.0). Set to -90 to disable.")
    parser.add_argument("--deesser", type=float, default=-20.0, help="De-esser threshold in dB (e.g. -20.0). Set to 0.0 to disable.")
    parser.add_argument("--gain", type=float, default=0.0, help="Master volume output make-up gain in dB")
    return parser.parse_args()

def change_speed_and_pitch(data, speed_factor, pitch_factor):
    """ Changes audio length based on speed and pitch multipliers. """
    total_factor = speed_factor * pitch_factor
    if total_factor == 1.0:
        return data # No change needed
    old_length = len(data)
    new_length = int(old_length / total_factor)
    old_indices = np.arange(old_length)
    new_indices = np.linspace(0, old_length - 1, new_length)
    return np.interp(new_indices, old_indices, data)

def apply_5_band_eq(data, fs, eq_gains):
    """ Splits audio into 5 distinct, non-overlapping bands and applies separate volume gains. """
    nyq = 0.5 * fs
    b0, a0 = butter(2, 150 / nyq, btype='low')
    b1, a1 = butter(2, [150 / nyq, 500 / nyq], btype='band')
    b2, a2 = butter(2, [500 / nyq, 2000 / nyq], btype='band')
    b3, a3 = butter(2, [2000 / nyq, 7000 / nyq], btype='band')
    b4, a4 = butter(2, 7000 / nyq, btype='high')

    gains = [10 ** (g / 20.0) for g in eq_gains]

    band0 = lfilter(b0, a0, data) * gains[0]
    band1 = lfilter(b1, a1, data) * gains[1]
    band2 = lfilter(b2, a2, data) * gains[2]
    band3 = lfilter(b3, a3, data) * gains[3]
    band4 = lfilter(b4, a4, data) * gains[4]

    return band0 + band1 + band2 + band3 + band4

def apply_noise_gate(data, fs, threshold_db):
    """ Mutes chunks of audio that fall below a certain volume threshold. """
    chunk_size_ms = 20
    chunk_samples = int(fs * (chunk_size_ms / 1000.0))
    output = np.copy(data)
    threshold_linear = 10 ** (threshold_db / 20.0)

    for i in range(0, len(data), chunk_samples):
        chunk = data[i : i + chunk_samples]
        if len(chunk) == 0:
            continue
        volume = np.sqrt(np.mean(chunk ** 2))
        if volume < threshold_linear:
            output[i : i + chunk_samples] = 0.0
    return output

def apply_deesser(data, fs, threshold_db, reduction_db=8.0):
    """
    Dynamically attenuates frequencies above 5kHz when they exceed a threshold.
    Uses perfectly split high/low filters to prevent phase cancellation.
    """
    nyq = 0.5 * fs
    
    # 1. Create a matching pair of filters to split the audio perfectly
    b_high, a_high = butter(2, 5000 / nyq, btype='high')
    b_low, a_low = butter(2, 5000 / nyq, btype='low')
    
    # Pre-filter the entire stream into distinct high and low layers
    high_band = lfilter(b_high, a_high, data)
    low_band = lfilter(b_low, a_low, data)
    
    # 2. Setup analysis variables
    chunk_samples = int(fs * 0.01)  # 10ms windows
    output = np.copy(low_band)      # Start with the untouchable low frequencies
    
    threshold_linear = 10 ** (threshold_db / 20.0)
    attenuation_factor = 10 ** (-reduction_db / 20.0)
    
    # 3. Process track chunk by chunk
    for i in range(0, len(data), chunk_samples):
        high_chunk = high_band[i : i + chunk_samples]
        if len(high_chunk) == 0:
            continue
            
        # Calculate the Root Mean Square (RMS) volume of the high frequencies
        high_volume = np.sqrt(np.mean(high_chunk ** 2))
        
        # If it triggers the threshold, squash the highs. If not, pass them through raw.
        if high_volume > threshold_linear:
            output[i : i + chunk_samples] += high_chunk * attenuation_factor
        else:
            output[i : i + chunk_samples] += high_chunk
            
    return output



def main():
    args = parse_parameters()

    # 1. Read input WAV file natively
    with wave.open(args.input, 'rb') as wav_in:
        params = wav_in.getparams()
        n_channels, sampwidth, framerate, n_frames = params[:4]
        raw_bytes = wav_in.readframes(n_frames)

        if sampwidth == 2:
            audio_stream = np.frombuffer(raw_bytes, dtype=np.int16).astype(np.float64) / 32768.0
        elif sampwidth == 1:
            audio_stream = (np.frombuffer(raw_bytes, dtype=np.uint8).astype(np.float64) - 128.0) / 128.0
        else:
            raise ValueError("Unsupported bit depth file. Please use standard 16-bit PCM WAV tracks.")

    print(f"[!] Processing voice data stream: {args.input}")

    # 2. Run Noise Gate
    if args.gate > -90.0:
        print(f"[*] Applying Noise Gate: {args.gate} dB")
        audio_stream = apply_noise_gate(audio_stream, framerate, args.gate)

    # [NEW] 2b. Run Dynamic De-esser
    if args.deesser < 0.0:
        print(f"[*] Applying Dynamic De-esser: Threshold={args.deesser} dB")
        audio_stream = apply_deesser(audio_stream, framerate, args.deesser)

    # 3. Run Speed & Pitch
    if args.speed != 1.0 or args.pitch != 1.0:
        print(f"[*] Modifying Timing/Pitch: Speed={args.speed}x, Pitch={args.pitch}x")
        audio_stream = change_speed_and_pitch(audio_stream, args.speed, args.pitch)

    # 4. Run 5-Band EQ
    print(f"[*] Applying EQ profile: {args.eq}")
    audio_stream = apply_5_band_eq(audio_stream, framerate, args.eq)

    # 5. Run Master Volume Gain Adjustment
    if args.gain != 0.0:
        print(f"[*] Applying Master Gain: {args.gain} dB")
        linear_gain = 10 ** (args.gain / 20.0)
        audio_stream = audio_stream * linear_gain

    # 6. Safety Peak Normalization Limiter
    max_peak = np.max(np.abs(audio_stream))
    if max_peak > 0.99:
        print("[*] Signal peaking! Automatically scaling down to safe levels.")
        audio_stream = (audio_stream / max_peak) * 0.95

    # 7. Safety Clip and Convert decimals back into writeable binary data integers
    audio_stream = np.clip(audio_stream, -1.0, 1.0)
    audio_out_int = (audio_stream * 32767.0).astype(np.int16)

    # 8. Output file naming logic
    input_base, _ = os.path.splitext(args.input)
    count = 1
    while True:
        out_filename = f"{input_base}_post_{count}.wav"
        if not os.path.exists(out_filename):
            break
        count += 1

    # 9. Save out the new WAV file
    with wave.open(out_filename, 'wb') as wav_out:
        wav_out.setparams((n_channels, sampwidth, framerate, len(audio_out_int), "NONE", "not compressed"))
        wav_out.writeframes(audio_out_int.tobytes())

    print(f"[Success] File saved: {out_filename}")

if __name__ == "__main__":
    main()
